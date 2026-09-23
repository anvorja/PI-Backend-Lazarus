"""Configuración de la sesión Gemini Live (HU-002)."""

import json

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.live_service import build_setup_message
from app.sockets import live_proxy as proxy_module
from tests.test_live_proxy import FakeGemini


def test_modelo_y_voz_por_defecto_vienen_de_la_configuracion():
    setup = build_setup_message()["setup"]

    assert setup["model"] == f"models/{settings.gemini_live_model}"
    voice = setup["generation_config"]["speech_config"]["voice_config"]
    assert voice["prebuilt_voice_config"]["voice_name"] == settings.gemini_live_voice
    assert setup["generation_config"]["response_modalities"] == ["AUDIO"]


def test_deteccion_de_voz_con_interrupcion_del_asistente():
    realtime = build_setup_message()["setup"]["realtime_input_config"]

    assert realtime["automatic_activity_detection"]["disabled"] is False
    assert realtime["activity_handling"] == "START_OF_ACTIVITY_INTERRUPTS"


def test_audio_proactivo_y_transcripcion_de_entrada_activos():
    setup = build_setup_message()["setup"]

    assert setup["proactivity"] == {"proactive_audio": True}
    assert "input_audio_transcription" in setup


def test_idioma_por_defecto_de_la_configuracion_si_la_app_no_lo_envia(monkeypatch):
    monkeypatch.setattr(settings, "gemini_live_language", "en")
    captured = {}

    def fake_prompt(language, *args, **kwargs):
        captured["language"] = language
        return "prompt"

    monkeypatch.setattr("app.services.live_service.get_live_system_prompt", fake_prompt)
    gemini = FakeGemini(incoming=[json.dumps({"setupComplete": {}})])
    monkeypatch.setattr(proxy_module.websockets, "connect", lambda *a, **k: gemini)

    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps({"type": "start"}))
        ws.receive_text()

    assert captured["language"] == "en"
