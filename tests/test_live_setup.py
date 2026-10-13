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


def test_audio_proactivo_y_transcripciones_de_entrada_y_salida_activos():
    setup = build_setup_message()["setup"]

    assert setup["proactivity"] == {"proactive_audio": True}
    assert "input_audio_transcription" in setup
    assert "output_audio_transcription" in setup


def test_get_location_declarada_sin_parametros():
    # HU-013: la ubicación solo viaja cuando el asistente la pide (regla 4).
    tools = build_setup_message()["setup"]["tools"][0]["function_declarations"]
    get_location = next(t for t in tools if t["name"] == "get_location")
    assert get_location["parameters"] == {"type": "object", "properties": {}}


def test_funciones_de_sos_declaradas():
    # HU-012: contacto por voz, alerta con confirmación y llamadas.
    tools = {
        t["name"]: t for t in build_setup_message()["setup"]["tools"][0]["function_declarations"]
    }
    assert tools["set_emergency_contact"]["parameters"]["required"] == ["name", "phone"]
    assert tools["trigger_sos"]["parameters"] == {"type": "object", "properties": {}}
    assert tools["cancel_sos"]["parameters"] == {"type": "object", "properties": {}}
    call = tools["call_phone"]["parameters"]
    assert call["properties"]["to"]["enum"] == ["contact", "emergency"]
    assert call["required"] == ["to"]


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


def test_get_time_declarada_sin_parametros():
    # LAZA-115: la hora la da el teléfono; el asistente no la conoce.
    tools = build_setup_message()["setup"]["tools"][0]["function_declarations"]
    get_time = next(t for t in tools if t["name"] == "get_time")
    assert get_time["parameters"] == {"type": "object", "properties": {}}


def test_get_heading_declarada_sin_parametros():
    # HU-016: el rumbo lo da la brújula del teléfono.
    tools = build_setup_message()["setup"]["tools"][0]["function_declarations"]
    get_heading = next(t for t in tools if t["name"] == "get_heading")
    assert get_heading["parameters"] == {"type": "object", "properties": {}}
    assert "needs_calibration" in get_heading["description"]


def test_add_note_declarada_con_el_texto():
    # HU-024: "anota que la rampa está bloqueada".
    tools = build_setup_message()["setup"]["tools"][0]["function_declarations"]
    add_note = next(t for t in tools if t["name"] == "add_note")
    assert add_note["parameters"]["required"] == ["text"]


def test_get_unicentro_route_declarada_sin_parametros():
    # HU-019: la regla horaria la decide la app; el asistente solo la consulta.
    tools = build_setup_message()["setup"]["tools"][0]["function_declarations"]
    route = next(t for t in tools if t["name"] == "get_unicentro_route")
    assert route["parameters"] == {"type": "object", "properties": {}}
    assert "Unicentro" in route["description"]
