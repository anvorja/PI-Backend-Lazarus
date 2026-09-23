"""Pruebas del proxy `/ws/live` con un Gemini Live simulado (sin red ni API key real)."""

import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close

from app.core.config import settings
from app.main import app
from app.sockets import live_proxy as proxy_module


class FakeGemini:
    """Doble de la conexión WebSocket con Gemini: registra lo enviado y emite `incoming`."""

    def __init__(self, incoming: list[str]):
        self.sent: list[str] = []
        self.closed = False
        self._incoming = list(incoming)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._incoming:
            return self._incoming.pop(0)
        while not self.closed:
            await asyncio.sleep(0.01)
        raise StopAsyncIteration


@pytest.fixture
def fake_gemini(monkeypatch):
    fake = FakeGemini(incoming=[json.dumps({"setupComplete": {}})])
    urls: list[str] = []

    def fake_connect(url, *args, **kwargs):
        urls.append(url)
        return fake

    monkeypatch.setattr(proxy_module.websockets, "connect", fake_connect)
    fake.urls = urls
    return fake


def _wait_for(condition, timeout: float = 2.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("la condición no se cumplió a tiempo")
        time.sleep(0.01)


def test_start_abre_sesion_con_setup_y_reenvia_setup_complete(fake_gemini):
    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps({"type": "start", "language": "es", "voice": "Kore"}))

        assert json.loads(ws.receive_text()) == {"setupComplete": {}}

    setup = json.loads(fake_gemini.sent[0])["setup"]
    assert setup["model"] == f"models/{settings.gemini_live_model}"
    assert setup["system_instruction"]["parts"][0]["text"]
    assert setup["tools"][0]["function_declarations"]
    voice = setup["generation_config"]["speech_config"]["voice_config"]
    assert voice["prebuilt_voice_config"]["voice_name"] == "Kore"


def test_reenvia_mensajes_de_la_app_hacia_gemini(fake_gemini):
    audio = json.dumps({"realtime_input": {"audio": {"data": "AAAA"}}})

    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps({"type": "start"}))
        ws.receive_text()
        ws.send_text(audio)
        _wait_for(lambda: audio in fake_gemini.sent)

    _wait_for(lambda: fake_gemini.closed)


def test_la_api_key_solo_viaja_hacia_gemini(fake_gemini):
    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps({"type": "start"}))
        recibido = ws.receive_text()

    assert settings.gemini_api_key in fake_gemini.urls[0]
    assert settings.gemini_api_key not in recibido


def test_sin_frame_start_cierra_con_1008(monkeypatch, fake_gemini):
    monkeypatch.setattr(proxy_module, "START_TIMEOUT_S", 0.1)

    with TestClient(app).websocket_connect("/ws/live") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()

    assert exc.value.code == 1008
    assert fake_gemini.sent == []


def test_frame_inicial_distinto_de_start_cierra_con_1008(fake_gemini):
    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps({"type": "hola"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()

    assert exc.value.code == 1008


def test_error_upstream_no_expone_la_api_key(monkeypatch, caplog):
    key = settings.gemini_api_key

    def failing_connect(url, *args, **kwargs):
        raise ConnectionError(f"no se pudo abrir {url}")

    monkeypatch.setattr(proxy_module.websockets, "connect", failing_connect)
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps({"type": "start"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()

    assert exc.value.code == proxy_module.CLOSE_UPSTREAM_ERROR
    assert key not in (exc.value.reason or "")
    assert key not in caplog.text


def test_sin_api_key_configurada_cierra_con_codigo_de_configuracion(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")

    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps({"type": "start"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()

    assert exc.value.code == proxy_module.CLOSE_MISCONFIGURED


class ClosingGemini(FakeGemini):
    """Gemini que, tras el setupComplete, cierra la conexión con un código dado."""

    def __init__(self, close: Close | None):
        super().__init__(incoming=[json.dumps({"setupComplete": {}})])
        self._close = close

    async def __anext__(self):
        if self._incoming:
            return self._incoming.pop(0)
        if self._close is None:
            raise StopAsyncIteration  # cierre ordenado
        raise ConnectionClosed(rcvd=self._close, sent=None)


def _close_code_after_setup(monkeypatch, gemini: FakeGemini) -> int:
    monkeypatch.setattr(proxy_module.websockets, "connect", lambda *a, **k: gemini)
    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps({"type": "start"}))
        ws.receive_text()  # setupComplete
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    return exc.value.code


def test_gemini_termina_la_sesion_cierra_con_4001(monkeypatch):
    code = _close_code_after_setup(monkeypatch, ClosingGemini(close=None))
    assert code == proxy_module.CLOSE_UPSTREAM_ENDED


def test_gemini_cierra_por_limite_cierra_con_4001(monkeypatch):
    code = _close_code_after_setup(monkeypatch, ClosingGemini(Close(1000, "session limit")))
    assert code == proxy_module.CLOSE_UPSTREAM_ENDED


def test_gemini_cierra_por_cuota_cierra_con_4003(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="uvicorn.error")
    gemini = ClosingGemini(Close(1011, "RESOURCE_EXHAUSTED: quota exceeded"))

    code = _close_code_after_setup(monkeypatch, gemini)

    assert code == proxy_module.CLOSE_QUOTA_EXCEEDED
    assert "quota" in caplog.text  # la causa queda registrada


def test_gemini_cierra_con_error_cierra_con_4002(monkeypatch):
    code = _close_code_after_setup(monkeypatch, ClosingGemini(Close(1011, "internal error")))
    assert code == proxy_module.CLOSE_UPSTREAM_ERROR


def test_duracion_maxima_cumplida_cierra_con_4001(monkeypatch, fake_gemini):
    monkeypatch.setattr(settings, "gemini_live_max_session_s", 0.2)

    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_text(json.dumps({"type": "start"}))
        ws.receive_text()  # setupComplete
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()

    assert exc.value.code == proxy_module.CLOSE_UPSTREAM_ENDED
    assert fake_gemini.closed
