"""Script de carga: sesiones simuladas contra un backend falso en localhost."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
import websockets

_SPEC = importlib.util.spec_from_file_location(
    "load_test", Path(__file__).resolve().parents[1] / "scripts" / "load_test.py"
)
load_test = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(load_test)


async def _fake_backend(received: list[dict]):
    async def handler(ws):
        async for raw in ws:
            frame = json.loads(raw)
            received.append(frame)
            if frame.get("type") == "start":
                await ws.send(json.dumps({"setupComplete": {}}))
            elif "client_content" in frame:
                await ws.send(json.dumps({"serverContent": {"modelTurn": {}}}))

    return await websockets.serve(handler, "127.0.0.1", 0)


def _args(port: int, *extra: str):
    return load_test.parse_args(
        [f"ws://127.0.0.1:{port}/ws/live", "--sessions", "3", "--duration", "1", *extra]
    )


def test_las_sesiones_simuladas_se_conectan_saludan_y_miden():
    received: list[dict] = []

    async def go():
        server = await _fake_backend(received)
        port = server.sockets[0].getsockname()[1]
        try:
            args = _args(port, "--operator", "Claro", "--transport", "cellular")
            return args, await load_test.run_load(args)
        finally:
            server.close()
            await server.wait_closed()

    args, results = asyncio.run(go())
    assert len(results) == 3
    assert all(r.setup_ms is not None and r.first_audio_ms is not None for r in results)
    assert all(r.sent_msgs > 3 and r.recv_msgs >= 2 for r in results)
    starts = [f for f in received if f.get("type") == "start"]
    assert len(starts) == 3
    assert starts[0]["network"] == {"operator": "Claro", "transport": "cellular"}
    assert "deviceToken" not in starts[0]
    summary = load_test.summarize(results, args)
    assert summary["sessions"] == 3 and summary["no_setup"] == 0
    assert summary["first_audio_ms"]["n"] == 3


def test_el_token_se_lee_del_entorno_y_no_se_imprime(monkeypatch, capsys):
    monkeypatch.setenv(load_test.TOKEN_ENV, "token-de-prueba")
    received: list[dict] = []

    async def go():
        server = await _fake_backend(received)
        port = server.sockets[0].getsockname()[1]
        try:
            await load_test.run_load(_args(port))
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(go())
    assert received[0]["deviceToken"] == "token-de-prueba"
    assert "token-de-prueba" not in capsys.readouterr().out


def test_un_servidor_remoto_exige_confirmar_el_gasto():
    with pytest.raises(SystemExit):
        load_test.parse_args(["wss://backend.ejemplo.com/ws/live"])
    ok = load_test.parse_args(["wss://backend.ejemplo.com/ws/live", "--confirm"])
    assert ok.sessions == 5


def test_el_tope_de_sesiones_se_respeta():
    with pytest.raises(SystemExit):
        load_test.parse_args(["ws://localhost:8000/ws/live", "--sessions", "500"])
    with pytest.raises(SystemExit):
        load_test.parse_args(["ws://localhost:8000/ws/live", "--sessions", "0"])


def test_un_backend_caido_se_registra_sin_romper_la_corrida():
    args = load_test.parse_args(["ws://127.0.0.1:9/ws/live", "--sessions", "2", "--duration", "1"])
    results = asyncio.run(load_test.run_load(args))
    assert all(r.error for r in results)
    assert load_test.summarize(results, args)["no_setup"] == 2
