// Panel del piloto (HU-046). El token de acceso vive solo en memoria; al
// recargar la página se renueva con la cookie HttpOnly del refresh.
"use strict";

const API = "/api/v1/admin";
let token = null;
let refreshTimer = null;

const $ = (id) => document.getElementById(id);

// Crea un elemento con texto (nunca HTML: los datos vienen de los teléfonos).
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
}

function button(label, onClick, cls) {
  const b = el("button", label, cls);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

async function refreshToken() {
  const r = await fetch(`${API}/refresh`, { method: "POST", credentials: "same-origin" });
  if (!r.ok) return false;
  const body = await r.json();
  token = body.access_token;
  $("who").textContent = body.username;
  return true;
}

async function api(path, options = {}, retry = true) {
  const r = await fetch(`${API}${path}`, {
    ...options,
    credentials: "same-origin",
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${token}`,
    },
  });
  if (r.status === 401 && retry && (await refreshToken())) return api(path, options, false);
  if (r.status === 401) {
    showLogin();
    throw new Error("Sesión vencida");
  }
  if (!r.ok) throw new Error(`Error ${r.status}`);
  return r.status === 204 ? null : r;
}

const json = async (path, options) => (await api(path, options)).json();

function showLogin() {
  clearInterval(refreshTimer);
  token = null;
  $("app").hidden = true;
  $("login").hidden = false;
}

function showApp() {
  $("login").hidden = true;
  $("app").hidden = false;
  loadAll();
  clearInterval(refreshTimer);
  refreshTimer = setInterval(loadAll, 15000);
}

// ---- Fechas y textos ---------------------------------------------------------

function local(iso) {
  if (!iso) return "—";
  // La API entrega UTC sin zona: se muestra en la hora de Colombia.
  const d = new Date(`${iso}Z`);
  return d.toLocaleString("es-CO", { timeZone: "America/Bogota", dateStyle: "short", timeStyle: "short" });
}

const STATUS = { pending: "Pendiente", approved: "Aprobado", disabled: "Deshabilitado" };
const CLOSE = {
  4001: "Gemini terminó", 4002: "Error de red", 4003: "Sin cuota", 4005: "Sin saldo",
  4006: "En pausa", 4009: "Minutos del día", 4010: "Cerrada desde el panel",
};

// ---- Servicio -----------------------------------------------------------------

let settings = null;

async function loadSettings() {
  settings = await json("/settings");
  const estado = $("estado");
  estado.textContent = settings.open_now
    ? "Abierto: los teléfonos aprobados pueden usar Lazarus ahora."
    : "Cerrado: nadie puede abrir una sesión ahora (no se gasta saldo).";
  estado.className = `estado ${settings.open_now ? "abierto" : "cerrado"}`;
  $("toggle-service").textContent = settings.service_open ? "Cerrar el servicio" : "Abrir el servicio";
  $("toggle-service").className = settings.service_open ? "danger" : "";
  const form = $("schedule-form");
  if (document.activeElement && form.contains(document.activeElement)) return; // no pisar lo que se edita
  form.enabled.checked = settings.schedule.enabled;
  form.from.value = settings.schedule.from;
  form.to.value = settings.schedule.to;
  form.querySelectorAll('input[name="day"]').forEach((c) => {
    c.checked = settings.schedule.days.includes(Number(c.value));
  });
}

$("toggle-service").addEventListener("click", async () => {
  await json("/settings", { method: "PUT", body: JSON.stringify({ service_open: !settings.service_open }) });
  loadSettings();
});

$("schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const days = [...form.querySelectorAll('input[name="day"]:checked')].map((c) => Number(c.value));
  await json("/settings", {
    method: "PUT",
    body: JSON.stringify({
      schedule: { enabled: form.enabled.checked, days, from: form.from.value, to: form.to.value },
    }),
  });
  form.querySelector("button").blur();
  loadSettings();
});

// ---- Dispositivos -------------------------------------------------------------

async function patch(id, body) {
  await json(`/devices/${id}`, { method: "PATCH", body: JSON.stringify(body) });
  loadDevices();
}

function deviceRow(d) {
  const tr = el("tr");
  const name = el("td");
  name.append(el("div", d.name || "(sin nombre)"));
  if (d.active) name.append(el("div", "● En sesión", "live"));
  tr.append(name);

  const st = el("td");
  st.append(el("span", STATUS[d.status] || d.status, `pill ${d.status}`));
  tr.append(st);

  const phone = el("td");
  phone.append(el("div", d.model || "—"));
  phone.append(el("div", `Android ${d.android || "?"} · app ${d.app_version || "?"}`, "small"));
  tr.append(phone);

  const seen = el("td");
  seen.append(el("div", local(d.last_seen_at)));
  seen.append(el("div", d.last_ip || "", "small"));
  tr.append(seen);

  tr.append(el("td", `${d.minutes_today} min`));
  tr.append(el("td", d.daily_minutes_limit ? `${d.daily_minutes_limit} min` : "Sin límite"));

  const logs = el("td");
  logs.append(el("div", `${d.uploads} subidas`));
  logs.append(el("div", d.upload_requested ? "Subida pedida" : local(d.last_upload_at), "small"));
  tr.append(logs);

  const actions = el("div", null, "actions");
  if (d.status !== "approved") actions.append(button("Aprobar", () => patch(d.id, { status: "approved" })));
  if (d.status === "approved") {
    actions.append(button("Deshabilitar", () => patch(d.id, { status: "disabled" }), "danger"));
  }
  actions.append(
    button("Nombre", () => {
      const value = prompt("Nombre del dispositivo (usa un seudónimo):", d.name);
      if (value !== null) patch(d.id, { name: value });
    }, "secondary"),
  );
  actions.append(
    button("Límite", () => {
      const value = prompt("Minutos por día (0 = sin límite):", d.daily_minutes_limit || 0);
      if (value !== null && !Number.isNaN(Number(value))) patch(d.id, { daily_minutes_limit: Number(value) });
    }, "secondary"),
  );
  actions.append(button("Pedir logs", () => patch(d.id, { upload_requested: true }), "secondary"));
  if (d.active) {
    actions.append(
      button("Cerrar sesión", async () => {
        await json(`/devices/${d.id}/close-session`, { method: "POST" });
        loadDevices();
      }, "danger"),
    );
  }
  actions.append(button("Detalle", () => showDetail(d), "secondary"));
  actions.append(
    button("Borrar", async () => {
      if (!confirm(`¿Borrar "${d.name || d.model}" con sus sesiones y logs?`)) return;
      await api(`/devices/${d.id}`, { method: "DELETE" });
      $("detail").hidden = true;
      loadDevices();
    }, "danger"),
  );
  const td = el("td");
  td.append(actions);
  tr.append(td);
  return tr;
}

async function loadDevices() {
  const devices = await json("/devices");
  const body = $("devices");
  body.replaceChildren(...devices.map(deviceRow));
  if (!devices.length) {
    const tr = el("tr");
    const td = el("td", "Todavía no hay teléfonos registrados.");
    td.colSpan = 8;
    tr.append(td);
    body.append(tr);
  }
}

async function showDetail(d) {
  $("detail").hidden = false;
  $("t-detalle").textContent = `Detalle · ${d.name || d.model}`;
  const box = $("detail-body");
  box.replaceChildren(el("p", "Cargando…", "small"));
  const [logs, sessions] = await Promise.all([
    json(`/devices/${d.id}/logs`),
    json(`/devices/${d.id}/sessions`),
  ]);
  const parts = [];

  const lat = logs.latency;
  parts.push(el("h3", "Latencia voz a voz"));
  parts.push(
    el("p", lat.count ? `${lat.count} respuestas · mediana ${lat.median_ms} ms · p90 ${lat.p90_ms} ms` : "Sin datos todavía."),
  );

  parts.push(el("h3", "Logs de campo"));
  if (logs.files.length) {
    const ul = el("ul");
    logs.files.forEach((f) => ul.append(el("li", `${f.name} · ${(f.size / 1024).toFixed(1)} KB`)));
    parts.push(ul);
    parts.push(
      button("Descargar todo (.zip)", async () => {
        const r = await api(`/devices/${d.id}/logs.zip`);
        const blob = await r.blob();
        const name = /filename="([^"]+)"/.exec(r.headers.get("content-disposition") || "")?.[1] || "logs.zip";
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = name;
        a.click();
        URL.revokeObjectURL(a.href);
      }),
    );
  } else {
    parts.push(el("p", "Este teléfono no ha subido logs.", "small"));
  }

  parts.push(el("h3", "Últimas sesiones"));
  if (sessions.length) {
    const table = el("table");
    const head = el("tr");
    ["Inicio", "Duración", "Cierre", "IP"].forEach((h) => head.append(el("th", h)));
    table.append(head);
    sessions.slice(0, 30).forEach((s) => {
      const tr = el("tr");
      tr.append(el("td", local(s.started_at)));
      tr.append(el("td", s.ended_at ? `${Math.round(s.duration_s / 60)} min` : "en curso"));
      tr.append(el("td", CLOSE[s.close_code] || (s.close_code ?? "—")));
      tr.append(el("td", s.ip));
      table.append(tr);
    });
    parts.push(table);
  } else {
    parts.push(el("p", "Sin sesiones.", "small"));
  }
  box.replaceChildren(...parts);
}

async function loadAll() {
  try {
    await Promise.all([loadSettings(), loadDevices()]);
  } catch (e) {
    console.warn(e);
  }
}

// ---- Entrada ------------------------------------------------------------------

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  $("login-error").textContent = "";
  const r = await fetch(`${API}/login`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: form.username.value, password: form.password.value }),
  });
  if (!r.ok) {
    $("login-error").textContent = r.status === 503 ? "El panel no está configurado." : "Usuario o contraseña incorrectos.";
    return;
  }
  const body = await r.json();
  token = body.access_token;
  $("who").textContent = body.username;
  form.password.value = "";
  showApp();
});

$("logout").addEventListener("click", async () => {
  await fetch(`${API}/logout`, { method: "POST", credentials: "same-origin" });
  showLogin();
});

(async () => {
  if (await refreshToken()) showApp();
  else showLogin();
})();
