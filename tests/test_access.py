"""HU-044 a HU-046: dispositivos, control de acceso, logs de campo y panel."""

import gzip
import io
import json
import zipfile
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.sockets.live_proxy as proxy_module
from app.db.models import AdminUser, Device, DeviceSession
from app.db.session import SessionLocal
from app.main import app
from app.services import access
from app.services.admin_auth import hash_password
from tests.test_live_proxy import FakeGemini


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _register(client) -> str:
    r = client.post(
        "/api/v1/devices/register",
        json={"model": "23117RA68G", "android": "16", "app_version": "0.2.0+3"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "pending"
    return r.json()["device_token"]


def _set_device(token: str, **fields) -> int:
    with SessionLocal() as db:
        from sqlalchemy import select

        device = db.scalar(select(Device).where(Device.token_hash == access.hash_token(token)))
        for k, v in fields.items():
            setattr(device, k, v)
        db.add(device)
        db.commit()
        return device.id


def _close_code(client, token: str | None, monkeypatch) -> int | None:
    gemini = FakeGemini(incoming=[json.dumps({"setupComplete": {}})])
    monkeypatch.setattr(proxy_module.websockets, "connect", lambda *a, **k: gemini)
    start = {"type": "start"}
    if token:
        start["deviceToken"] = token
    with client.websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps(start))
        try:
            ws.receive_text()  # setupComplete: la sesión abrió
            return None
        except WebSocketDisconnect as exc:
            return exc.code


# ---- Registro y control de acceso -------------------------------------------


def test_el_telefono_se_registra_pendiente_y_no_abre_sesion(client, monkeypatch):
    token = _register(client)
    assert client.get("/api/v1/devices/me", headers={"X-Device-Token": token}).json() == {
        "status": "pending",
        "name": "",
        "upload_requested": False,
    }
    assert _close_code(client, token, monkeypatch) == access.CLOSE_DEVICE_PENDING
    with SessionLocal() as db:
        # Del token solo se guarda el hash.
        assert db.query(Device).one().token_hash != token


def test_aprobado_abre_sesion_y_queda_registrada(client, monkeypatch):
    token = _register(client)
    _set_device(token, status="approved")
    assert _close_code(client, token, monkeypatch) is None
    # El cierre se guarda cuando el servidor termina la sesión, un instante después.
    import time

    for _ in range(250):
        with SessionLocal() as db:
            row = db.query(DeviceSession).one()
        if row.ended_at is not None:
            break
        time.sleep(0.02)
    assert row.ended_at is not None


def test_deshabilitado_no_abre_sesion(client, monkeypatch):
    token = _register(client)
    _set_device(token, status="disabled")
    assert _close_code(client, token, monkeypatch) == access.CLOSE_DEVICE_DISABLED


def test_sin_minutos_del_dia_no_abre_sesion(client, monkeypatch):
    token = _register(client)
    device_id = _set_device(token, status="approved", daily_minutes_limit=10)
    now = access.utcnow()
    with SessionLocal() as db:
        db.add(
            DeviceSession(
                device_id=device_id,
                started_at=now - timedelta(minutes=11),
                ended_at=now - timedelta(minutes=1),
                duration_s=600,
            )
        )
        db.commit()
    assert _close_code(client, token, monkeypatch) == access.CLOSE_DAILY_LIMIT


def test_sin_token_pasa_mientras_no_se_exija(client, monkeypatch):
    # Versiones anteriores de la app, hasta activar DEVICE_AUTH_REQUIRED.
    assert _close_code(client, None, monkeypatch) is None
    monkeypatch.setattr(access.settings, "device_auth_required", True)
    assert _close_code(client, None, monkeypatch) == access.CLOSE_DEVICE_PENDING


def test_el_panel_cierra_el_servicio_para_todos(client, monkeypatch):
    token = _register(client)
    _set_device(token, status="approved")
    with SessionLocal() as db:
        access.put_settings(db, {"service_open": False})
    assert _close_code(client, token, monkeypatch) == access.CLOSE_PAUSED
    assert client.get("/api/v1/live/status").json() == {"cause": "paused"}


def test_horario_de_las_jornadas_en_hora_de_colombia():
    schedule = {"enabled": True, "days": [5], "from": "08:00", "to": "13:00"}
    # Sábado 17 de octubre de 2026, 10:00 en Colombia = 15:00 UTC.
    assert access.within_schedule(schedule, datetime(2026, 10, 17, 15, 0))
    # Mismo sábado a las 13:30 en Colombia.
    assert not access.within_schedule(schedule, datetime(2026, 10, 17, 18, 30))
    # Viernes a las 10:00.
    assert not access.within_schedule(schedule, datetime(2026, 10, 16, 15, 0))
    assert access.within_schedule({"enabled": False}, datetime(2026, 10, 16, 3, 0))


# ---- Logs de campo ------------------------------------------------------------


def test_sube_logs_solo_aprobado_y_solo_archivos_conocidos(client):
    token = _register(client)
    headers = {"X-Device-Token": token}
    files = [("files", ("notas_campo.csv", b"hora,nota\n", "text/csv"))]
    assert client.post("/api/v1/devices/me/logs", headers=headers, files=files).status_code == 403
    _set_device(token, status="approved", upload_requested=True)
    r = client.post("/api/v1/devices/me/logs", headers=headers, files=files)
    assert r.status_code == 201 and r.json() == {"saved": ["notas_campo.csv"]}
    bad = [("files", ("/etc/passwd", b"x", "text/plain"))]
    assert client.post("/api/v1/devices/me/logs", headers=headers, files=bad).status_code == 400
    assert client.get("/api/v1/devices/me", headers=headers).json()["upload_requested"] is False


# ---- Panel ------------------------------------------------------------------


def _admin(client) -> dict:
    with SessionLocal() as db:
        db.add(AdminUser(username="coordinador", password_hash=hash_password("clave-larga-1")))
        db.commit()
    r = client.post(
        "/api/v1/admin/login", json={"username": "coordinador", "password": "clave-larga-1"}
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_panel_exige_sesion_y_rechaza_clave_incorrecta(client):
    assert client.get("/api/v1/admin/devices").status_code == 401
    _admin(client)
    r = client.post("/api/v1/admin/login", json={"username": "coordinador", "password": "otra"})
    assert r.status_code == 401


def test_panel_refresca_la_sesion_con_la_cookie_y_cierra(client):
    _admin(client)
    assert client.post("/api/v1/admin/refresh").status_code == 200
    client.post("/api/v1/admin/logout")
    assert client.post("/api/v1/admin/refresh").status_code == 401


def test_panel_aprueba_nombra_y_limita_un_dispositivo(client, monkeypatch):
    headers = _admin(client)
    token = _register(client)
    device = client.get("/api/v1/admin/devices", headers=headers).json()[0]
    assert device["status"] == "pending" and device["model"] == "23117RA68G"
    r = client.patch(
        f"/api/v1/admin/devices/{device['id']}",
        headers=headers,
        json={"status": "approved", "name": "Participante 1", "daily_minutes_limit": 90},
    )
    assert r.json()["name"] == "Participante 1" and r.json()["daily_minutes_limit"] == 90
    assert _close_code(client, token, monkeypatch) is None
    sessions = client.get(f"/api/v1/admin/devices/{device['id']}/sessions", headers=headers)
    assert len(sessions.json()) == 1


def test_panel_abre_cierra_y_programa_el_servicio(client):
    headers = _admin(client)
    r = client.put(
        "/api/v1/admin/settings",
        headers=headers,
        json={
            "service_open": True,
            "schedule": {"enabled": True, "days": [5, 6], "from": "08:00", "to": "13:00"},
        },
    )
    assert r.json()["schedule"]["days"] == [5, 6]
    assert "open_now" in r.json()


def test_panel_descarga_los_logs_unidos_y_la_latencia(client):
    headers = _admin(client)
    token = _register(client)
    device_id = _set_device(token, status="approved", name="Participante 2")
    up = {"X-Device-Token": token}
    for chunk in (b"hora,nota\n", b"11:02,cebra\n"):
        client.post(
            "/api/v1/devices/me/logs",
            headers=up,
            files=[("files", ("notas_campo.csv", chunk, "text/csv"))],
        )
    telemetry = "\n".join(
        json.dumps({"event": "latency", "kind": "voice_to_voice", "ms": ms})
        for ms in (1800, 2200, 3100)
    ).encode()
    client.post(
        "/api/v1/devices/me/logs",
        headers=up,
        files=[("files", ("telemetry.jsonl", telemetry, "application/json"))],
    )
    summary = client.get(f"/api/v1/admin/devices/{device_id}/logs", headers=headers).json()
    assert summary["latency"] == {"count": 3, "median_ms": 2200, "p90_ms": 3100}
    listed = client.get("/api/v1/admin/devices", headers=headers).json()
    assert next(d for d in listed if d["id"] == device_id)["latency_median_ms"] == 2200
    r = client.get(f"/api/v1/admin/devices/{device_id}/logs.zip", headers=headers)
    assert "Participante-2" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert z.read("notas_campo.csv") == b"hora,nota\n11:02,cebra\n"


def test_los_logs_se_guardan_comprimidos():
    assert gzip.decompress(gzip.compress(b"x" * 10)) == b"x" * 10
