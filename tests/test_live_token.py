"""HU-031 (LAZA-67): sesión directa con Gemini Live mediante un token efímero."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import DeviceSession
from app.db.session import SessionLocal
from app.main import app
from app.services import access, live_token
from app.services.live_service import build_setup_message
from app.sockets import live_proxy
from tests.test_access import _register, _set_device


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def tokens(monkeypatch):
    """Sustituye la llamada a Gemini y guarda lo que se pidió."""
    calls: list[tuple[dict, float]] = []

    def fake(setup, ttl):
        calls.append((setup, ttl))
        return f"auth_tokens/prueba-{len(calls)}"

    monkeypatch.setattr(settings, "live_direct_enabled", True)
    monkeypatch.setattr(live_token, "create_token", fake)
    return calls


def _approved(client) -> tuple[str, dict]:
    token = _register(client)
    _set_device(token, status="approved")
    return token, {"X-Device-Token": token}


def test_desactivado_responde_404_y_la_app_usa_el_proxy(client, monkeypatch):
    monkeypatch.setattr(settings, "live_direct_enabled", False)
    assert client.post("/api/v1/live/token", json={}).status_code == 404


def test_emite_un_token_con_el_prompt_del_servidor(client, tokens):
    _, headers = _approved(client)
    r = client.post(
        "/api/v1/live/token",
        headers=headers,
        json={"language": "es", "assistantName": "Aria", "screenLocked": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"] == "auth_tokens/prueba-1"
    assert body["url"].endswith("BidiGenerateContentConstrained")
    assert body["model"] == f"models/{settings.gemini_live_model}"
    assert body["session_id"] is not None
    # La clave del servicio nunca sale del servidor.
    assert settings.gemini_api_key not in r.text if settings.gemini_api_key else True
    setup, ttl = tokens[0]
    assert setup == build_setup_message("es", None, "Aria", screen_locked=True)
    assert ttl == settings.live_token_ttl_s
    with SessionLocal() as db:
        row = db.get(DeviceSession, body["session_id"])
        assert row.mode == "direct" and row.ended_at is None


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"status": "pending"}, access.CLOSE_DEVICE_PENDING),
        ({"status": "disabled"}, access.CLOSE_DEVICE_DISABLED),
    ],
)
def test_rechaza_igual_que_el_proxy(client, tokens, fields, code):
    token = _register(client)
    _set_device(token, **fields)
    r = client.post("/api/v1/live/token", headers={"X-Device-Token": token}, json={})
    assert r.status_code == 403
    assert r.json()["code"] == code
    assert tokens == []


def test_con_el_servicio_en_pausa_no_emite(client, tokens, monkeypatch):
    _, headers = _approved(client)
    monkeypatch.setattr(settings, "live_enabled", False)
    r = client.post("/api/v1/live/token", headers=headers, json={})
    assert r.json()["code"] == access.CLOSE_PAUSED
    assert tokens == []


def test_la_vida_del_token_no_pasa_de_los_minutos_del_dia(client, tokens):
    token, headers = _approved(client)
    _set_device(token, daily_minutes_limit=10)
    assert client.post("/api/v1/live/token", headers=headers, json={}).status_code == 200
    assert tokens[0][1] == 600


def test_minutos_agotados_rechaza(client, tokens):
    token, headers = _approved(client)
    device_id = _set_device(token, daily_minutes_limit=1)
    now = access.utcnow()
    with SessionLocal() as db:
        db.add(DeviceSession(device_id=device_id, started_at=now, ended_at=now, duration_s=120.0))
        db.commit()
    r = client.post("/api/v1/live/token", headers=headers, json={})
    assert r.json()["code"] == access.CLOSE_DAILY_LIMIT


def test_la_app_cierra_la_sesion_y_cuenta_los_minutos(client, tokens):
    token, headers = _approved(client)
    session_id = client.post("/api/v1/live/token", headers=headers, json={}).json()["session_id"]
    other = _register(client)
    r = client.post(
        f"/api/v1/live/sessions/{session_id}/end",
        headers={"X-Device-Token": other},
        json={"closeCode": 4001},
    )
    assert r.status_code == 404  # solo el teléfono dueño de la sesión
    r = client.post(
        f"/api/v1/live/sessions/{session_id}/end", headers=headers, json={"closeCode": 4001}
    )
    assert r.status_code == 204
    with SessionLocal() as db:
        row = db.get(DeviceSession, session_id)
        assert row.ended_at is not None and row.close_code == 4001


def test_una_sesion_sin_cierre_se_cierra_al_pedir_otro_token(client, tokens):
    token, headers = _approved(client)
    first = client.post("/api/v1/live/token", headers=headers, json={}).json()["session_id"]
    with SessionLocal() as db:
        row = db.get(DeviceSession, first)
        row.started_at = access.utcnow() - timedelta(hours=2)
        db.commit()
    client.post("/api/v1/live/token", headers=headers, json={})
    with SessionLocal() as db:
        row = db.get(DeviceSession, first)
        # Se cuenta hasta la vida del token, no las dos horas.
        assert row.duration_s == settings.live_token_ttl_s


def test_sin_saldo_informado_por_la_app_se_ve_en_el_estado(client, tokens):
    _, headers = _approved(client)
    session_id = client.post("/api/v1/live/token", headers=headers, json={}).json()["session_id"]
    client.post(
        f"/api/v1/live/sessions/{session_id}/end",
        headers=headers,
        json={"closeCode": live_proxy.CLOSE_BILLING},
    )
    assert client.get("/api/v1/live/status").json()["cause"] == "billing"
    live_proxy._last_failure = None


def test_si_gemini_no_emite_el_token_responde_502(client, monkeypatch):
    monkeypatch.setattr(settings, "live_direct_enabled", True)

    def boom(*_):
        raise RuntimeError("sin red")

    monkeypatch.setattr(live_token, "create_token", boom)
    _, headers = _approved(client)
    r = client.post("/api/v1/live/token", headers=headers, json={})
    assert r.status_code == 502


def test_la_configuracion_del_token_es_la_del_proxy():
    setup = build_setup_message("es")
    config = live_token.setup_to_config(setup)
    s = setup["setup"]
    assert config["system_instruction"] == s["system_instruction"]["parts"][0]["text"]
    assert config["tools"] == s["tools"]
    assert config["speech_config"] == s["generation_config"]["speech_config"]
    assert config["proactivity"] == {"proactive_audio": True}


def test_el_token_es_de_un_uso_y_bloquea_la_configuracion(monkeypatch):
    seen: dict = {}

    class FakeTokens:
        def create(self, config):
            seen.update(config)
            return type("T", (), {"name": "auth_tokens/x"})()

    class FakeClient:
        def __init__(self, api_key, http_options):
            seen["api_version"] = http_options["api_version"]
            self.auth_tokens = FakeTokens()

    monkeypatch.setattr(settings, "gemini_api_key", "clave-de-prueba")
    monkeypatch.setattr(live_token.genai, "Client", FakeClient)
    assert live_token.create_token(build_setup_message("es"), 600) == "auth_tokens/x"
    assert seen["uses"] == 1
    assert seen["lock_additional_fields"] == []
    assert (seen["expire_time"] - seen["new_session_expire_time"]).total_seconds() == 540
    assert seen["live_connect_constraints"]["model"] == settings.gemini_live_model
