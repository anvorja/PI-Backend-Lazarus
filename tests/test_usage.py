"""Alertas de consumo (HU-051, LAZA-124): transferencia del mes, minutos de Live,
aviso al 80 % y prueba de la conexión con Gemini."""

import json
from datetime import datetime

import psutil
import pytest
import websockets
from fastapi.testclient import TestClient

from app.db.models import AdminUser, Device, DeviceSession, UsageDay
from app.db.session import SessionLocal
from app.main import app
from app.services import metrics, usage
from app.services.admin_auth import hash_password

_GB = 1_000_000_000


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_counters():
    metrics._bytes_up = metrics._bytes_down = 0
    metrics._stored_up = metrics._stored_down = 0
    yield


def _admin(client) -> dict:
    with SessionLocal() as db:
        db.add(AdminUser(username="coordinador", password_hash=hash_password("clave-larga-1")))
        db.commit()
    r = client.post(
        "/api/v1/admin/login", json={"username": "coordinador", "password": "clave-larga-1"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _session(started: datetime, minutes: float) -> None:
    with SessionLocal() as db:
        device = Device(token_hash=f"h{started.isoformat()}", name="Prueba", created_at=started)
        db.add(device)
        db.flush()
        db.add(
            DeviceSession(
                device_id=device.id,
                started_at=started,
                ended_at=started,
                duration_s=minutes * 60,
            )
        )
        db.commit()


def test_el_trafico_se_acumula_por_dia_de_colombia():
    with SessionLocal() as db:
        # 02:00 UTC del 30-oct es todavía 29-oct en Colombia.
        usage.add_day_bytes(db, datetime(2026, 10, 30, 2), up=100, down=50)
        usage.add_day_bytes(db, datetime(2026, 10, 29, 20), up=10, down=5)
        usage.add_day_bytes(db, datetime(2026, 10, 30, 6), up=1, down=1)
        db.commit()
        day29 = db.get(UsageDay, "2026-10-29")
        assert (day29.bytes_up, day29.bytes_down) == (110, 55)
        assert db.get(UsageDay, "2026-10-30").bytes_up == 1


def test_el_muestreador_guarda_el_total_diario():
    metrics.add_bytes(up=4000, down=1000)
    sample, _, _ = metrics.take_sample(psutil.Process(), 0, 0, 0.0, 30.0)
    assert metrics.pending_bytes() == (4000, 1000)
    metrics._store(sample, purge=False)
    assert metrics.pending_bytes() == (0, 0)
    with SessionLocal() as db:
        row = db.get(UsageDay, usage.day_key(sample.ts))
        assert (row.bytes_up, row.bytes_down) == (4000, 1000)


def test_consumo_del_mes_y_niveles_de_aviso():
    now = datetime(2026, 10, 29, 23)  # 18:00 en Colombia
    with SessionLocal() as db:
        db.add(UsageDay(day="2026-10-05", bytes_up=50 * _GB, bytes_down=35 * _GB))
        db.add(UsageDay(day="2026-09-30", bytes_up=90 * _GB, bytes_down=0))  # otro mes
        db.commit()
    _session(datetime(2026, 10, 28, 18), minutes=90)
    _session(datetime(2026, 9, 30, 18), minutes=500)  # otro mes
    with SessionLocal() as db:
        out = usage.monthly_usage(
            db, now, {"transfer_gb": 100, "live_minutes": 100, "warn_pct": 80}
        )
    assert out["month"] == "2026-10"
    assert out["transfer"]["used_gb"] == 85
    assert out["transfer"]["pct"] == 85
    assert out["transfer"]["level"] == "warn"
    assert out["live"]["minutes"] == 90
    assert out["live"]["sessions"] == 1
    assert out["live"]["level"] == "warn"
    with SessionLocal() as db:
        unset = usage.monthly_usage(db, now, {"transfer_gb": 50, "live_minutes": 0, "warn_pct": 80})
    assert unset["transfer"]["level"] == "limit"
    assert unset["live"]["level"] == "unset"
    assert unset["live"]["pct"] is None


def test_el_mes_empieza_a_medianoche_de_colombia():
    # 1-nov 03:00 UTC es todavía 31-oct en Colombia: el mes es octubre.
    assert usage.month_start(datetime(2026, 11, 1, 3)) == datetime(2026, 10, 1, 5)
    assert usage.month_start(datetime(2026, 11, 1, 6)) == datetime(2026, 11, 1, 5)


def test_el_panel_ve_el_consumo_y_cambia_los_limites(client):
    headers = _admin(client)
    assert client.get("/api/v1/admin/usage").status_code == 401
    r = client.get("/api/v1/admin/usage", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["limits"] == {"transfer_gb": 100, "live_minutes": 0, "warn_pct": 80}
    assert body["transfer"]["level"] == "ok"
    assert body["live"]["level"] == "unset"
    assert body["last_failure"] is None

    r = client.put(
        "/api/v1/admin/settings",
        headers=headers,
        json={"usage_limits": {"transfer_gb": 100, "live_minutes": 600, "warn_pct": 75}},
    )
    assert r.status_code == 200
    assert r.json()["usage_limits"]["live_minutes"] == 600
    assert client.get("/api/v1/admin/usage", headers=headers).json()["warn_pct"] == 75
    # El servicio y el horario no cambian al guardar los límites.
    assert r.json()["service_open"] is True


def test_el_panel_ve_la_falla_de_facturacion_reciente(client, monkeypatch):
    headers = _admin(client)
    import app.sockets.live_proxy as proxy

    monkeypatch.setattr(proxy, "last_upstream_failure", lambda token=None: "billing")
    assert client.get("/api/v1/admin/usage", headers=headers).json()["last_failure"] == "billing"


class _FakeGemini:
    def __init__(self, reply=None, close=None):
        self.reply, self.close = reply, close
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        if self.close is not None:
            raise self.close
        return self.reply


def _closed(code: int, reason: str) -> websockets.ConnectionClosed:
    return websockets.ConnectionClosed(websockets.frames.Close(code, reason), None)


@pytest.mark.parametrize(
    ("fake", "status"),
    [
        (_FakeGemini(reply='{"setupComplete": {}}'), "ok"),
        (
            _FakeGemini(close=_closed(1011, "Your prepayment credits are depleted.")),
            "billing",
        ),
        (_FakeGemini(close=_closed(1011, "Quota exceeded for this model.")), "quota"),
        (_FakeGemini(close=_closed(1008, "Model not found.")), "error"),
    ],
)
def test_probar_gemini_dice_si_conecta_o_por_que_no(client, monkeypatch, fake, status):
    headers = _admin(client)
    monkeypatch.setattr(usage.websockets, "connect", lambda *a, **k: fake)
    r = client.post("/api/v1/admin/usage/check", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == status
    # Solo el setup: sin audio ni imágenes, no gasta minutos.
    assert list(fake.sent[0]) == ["setup"]
    assert "clave-de-prueba" not in r.text


def test_probar_gemini_requiere_admin(client):
    assert client.post("/api/v1/admin/usage/check").status_code == 401


def test_la_clave_no_aparece_en_el_detalle(monkeypatch):
    def boom(*a, **k):
        raise OSError("fallo al conectar a wss://x?key=clave-de-prueba")

    monkeypatch.setattr(usage.websockets, "connect", boom)
    import asyncio

    out = asyncio.run(usage.check_gemini())
    assert out["status"] == "error"
    assert "clave-de-prueba" not in out["detail"]
