"""Operador y tipo de red de cada sesión: el frame `start` -> la sesión -> el panel."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

import app.sockets.live_proxy as proxy_module
from app.db import session as db_session
from app.db.models import DeviceSession
from app.db.session import SessionLocal
from app.main import app
from app.sockets.live_proxy import parse_network
from tests.test_access import _admin, _register, _set_device
from tests.test_live_proxy import FakeGemini


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_parse_network_acepta_operador_y_tipo_validos():
    assert parse_network({"operator": "Claro", "transport": "cellular"}) == ("Claro", "cellular")


def test_parse_network_descarta_lo_invalido_sin_fallar():
    assert parse_network(None) == ("", "")
    assert parse_network("Claro") == ("", "")
    assert parse_network({"operator": 7, "transport": ["wifi"]}) == ("", "")
    assert parse_network({"operator": "Movistar", "transport": "satelite"}) == ("Movistar", "")


def test_parse_network_limpia_y_recorta_el_operador():
    carrier, _ = parse_network({"operator": "  Mov\x00is\ntar " + "x" * 80})
    assert carrier.startswith("Movis") and "\x00" not in carrier and "\n" not in carrier
    assert len(carrier) <= 40


def _open_session(client, monkeypatch, token: str, network) -> None:
    gemini = FakeGemini(incoming=[json.dumps({"setupComplete": {}})])
    monkeypatch.setattr(proxy_module.websockets, "connect", lambda *a, **k: gemini)
    start = {"type": "start", "deviceToken": token}
    if network is not None:
        start["network"] = network
    with client.websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps(start))
        ws.receive_text()
    for _ in range(250):  # el cierre se guarda un instante después
        with SessionLocal() as db:
            row = db.query(DeviceSession).one()
        if row.ended_at is not None:
            return
        time.sleep(0.02)


def test_la_sesion_guarda_el_operador_y_el_panel_lo_muestra(client, monkeypatch):
    token = _register(client)
    device_id = _set_device(token, status="approved")
    _open_session(client, monkeypatch, token, {"operator": "Claro", "transport": "cellular"})
    headers = _admin(client)
    rows = client.get(f"/api/v1/admin/devices/{device_id}/sessions", headers=headers).json()
    assert (rows[0]["carrier"], rows[0]["transport"]) == ("Claro", "cellular")


def test_una_app_anterior_sin_network_abre_sesion_igual(client, monkeypatch):
    token = _register(client)
    device_id = _set_device(token, status="approved")
    _open_session(client, monkeypatch, token, None)
    headers = _admin(client)
    rows = client.get(f"/api/v1/admin/devices/{device_id}/sessions", headers=headers).json()
    assert (rows[0]["carrier"], rows[0]["transport"]) == ("", "")


def test_init_db_agrega_las_columnas_a_una_base_que_ya_existia(tmp_path, monkeypatch):
    old = create_engine(f"sqlite:///{tmp_path}/vieja.db")
    with old.begin() as conn:
        conn.execute(text("CREATE TABLE device_sessions (id INTEGER PRIMARY KEY, ip VARCHAR(64))"))
        conn.execute(text("INSERT INTO device_sessions (id, ip) VALUES (1, '1.2.3.4')"))
    monkeypatch.setattr(db_session, "engine", old)
    db_session._add_missing_columns()
    db_session._add_missing_columns()  # repetirlo no falla
    names = {c["name"] for c in inspect(old).get_columns("device_sessions")}
    assert {"carrier", "transport"} <= names
    with old.connect() as conn:
        assert conn.execute(text("SELECT carrier, transport FROM device_sessions")).one() == (
            "",
            "",
        )
