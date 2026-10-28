"""Prueba de carga del proxy `/ws/live`: N teléfonos simulados contra un backend.

Cada sesión simulada hace lo mismo que la app: abre el WebSocket, manda el frame
`start` (con el operador y el tipo de red si se indican), espera `setupComplete`,
dispara el saludo `[INICIO]` y sigue enviando audio PCM de 16 kHz (silencio) cada
`--audio-ms` milisegundos y, si se da una foto, un JPEG por segundo.

Mide por sesión: tiempo de conexión, tiempo hasta `setupComplete`, latencia al
primer audio tras el saludo, mensajes y bytes en ambos sentidos y cómo terminó.
Al final imprime un resumen y, con `--out`, lo guarda en JSON para comparar
corridas (Render vs AWS) con los mismos parámetros.

OJO: contra un backend con Gemini real, cada sesión abre una sesión de Gemini Live
y gasta saldo y cuota. Por eso hay tope de sesiones y, fuera de localhost, hace
falta `--confirm`. Úsalo desde el mismo equipo y la misma red en cada corrida.

Uso (no necesita `.env` ni importa nada de `app`):

    uv run python scripts/load_test.py wss://MI-BACKEND/ws/live \
        --sessions 10 --duration 60 --ramp 10 --label render --confirm

El token de un teléfono aprobado (si el servidor exige dispositivos aprobados)
se lee de la variable de entorno LOAD_DEVICE_TOKEN; nunca va en la línea de
comandos ni se imprime.
"""

import argparse
import asyncio
import base64
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import websockets

MAX_SESSIONS = 200
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
KICKOFF = "[INICIO]"
TOKEN_ENV = "LOAD_DEVICE_TOKEN"


@dataclass
class SessionResult:
    index: int
    connect_ms: float | None = None
    setup_ms: float | None = None
    first_audio_ms: float | None = None  # del saludo a la primera respuesta
    sent_msgs: int = 0
    sent_bytes: int = 0
    recv_msgs: int = 0
    recv_bytes: int = 0
    duration_s: float = 0.0
    close_code: int | None = None
    error: str = ""
    notes: list[str] = field(default_factory=list)


def _ms(since: float) -> float:
    return round((time.monotonic() - since) * 1000, 1)


def start_frame(args: argparse.Namespace, token: str | None) -> dict:
    frame: dict = {"type": "start", "language": args.language}
    if token:
        frame["deviceToken"] = token
    network = {}
    if args.operator:
        network["operator"] = args.operator
    if args.transport:
        network["transport"] = args.transport
    if network:
        frame["network"] = network
    return frame


def audio_frame(ms: int) -> str:
    """Silencio PCM de 16 kHz, 16 bits, mono, de `ms` milisegundos."""
    pcm = bytes(16000 * 2 * ms // 1000)
    return json.dumps(
        {
            "realtime_input": {
                "media_chunks": [{"mime_type": "audio/pcm", "data": base64.b64encode(pcm).decode()}]
            }
        }
    )


def image_frame(data: bytes) -> str:
    return json.dumps(
        {
            "realtime_input": {
                "media_chunks": [
                    {"mime_type": "image/jpeg", "data": base64.b64encode(data).decode()}
                ]
            }
        }
    )


def kickoff_frame() -> str:
    return json.dumps(
        {
            "client_content": {
                "turns": [{"role": "user", "parts": [{"text": KICKOFF}]}],
                "turn_complete": True,
            }
        }
    )


async def run_session(
    index: int, args: argparse.Namespace, token: str | None, image: bytes | None
) -> SessionResult:
    result = SessionResult(index=index)
    started = time.monotonic()
    state = {"setup_at": None, "kickoff_at": None}

    async def send(ws, text: str) -> None:
        await ws.send(text)
        result.sent_msgs += 1
        result.sent_bytes += len(text)

    async def reader(ws) -> None:
        async for message in ws:
            result.recv_msgs += 1
            result.recv_bytes += len(message)
            text = message if isinstance(message, str) else message.decode("utf-8", "replace")
            if state["setup_at"] is None and "setupComplete" in text:
                state["setup_at"] = time.monotonic()
                result.setup_ms = _ms(started) - (result.connect_ms or 0)
            elif (
                state["kickoff_at"] is not None
                and result.first_audio_ms is None
                and "setupComplete" not in text
            ):
                result.first_audio_ms = _ms(state["kickoff_at"])

    async def sender(ws) -> None:
        while state["setup_at"] is None:
            await asyncio.sleep(0.05)
        if not args.no_kickoff:
            state["kickoff_at"] = time.monotonic()
            await send(ws, kickoff_frame())
        next_image = time.monotonic()
        audio = audio_frame(args.audio_ms)
        while True:
            await send(ws, audio)
            if image is not None and time.monotonic() >= next_image:
                await send(ws, image_frame(image))
                next_image += 1.0
            await asyncio.sleep(args.audio_ms / 1000)

    try:
        connecting = time.monotonic()
        async with websockets.connect(args.url, max_size=None, open_timeout=15) as ws:
            result.connect_ms = _ms(connecting)
            await send(ws, json.dumps(start_frame(args, token)))
            tasks = [asyncio.create_task(reader(ws)), asyncio.create_task(sender(ws))]
            try:
                await asyncio.wait(
                    tasks, timeout=args.duration, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                for task in tasks:
                    task.cancel()
                for task in tasks:
                    try:
                        await task
                    except (asyncio.CancelledError, websockets.ConnectionClosed):
                        pass
            if ws.close_code is not None:
                result.close_code = ws.close_code
            await ws.close()
    except websockets.ConnectionClosed as exc:
        result.close_code = exc.rcvd.code if exc.rcvd else 1006
    except Exception as exc:  # noqa: BLE001 — se registra y la corrida sigue
        result.error = type(exc).__name__
    result.duration_s = round(time.monotonic() - started, 1)
    if state["setup_at"] is None and not result.error:
        result.notes.append("nunca llegó setupComplete")
    return result


async def run_load(args: argparse.Namespace) -> list[SessionResult]:
    token = os.environ.get(TOKEN_ENV) or None
    image = Path(args.image_file).read_bytes() if args.image_file else None
    delay = args.ramp / args.sessions if args.sessions > 1 else 0
    tasks = []
    for i in range(args.sessions):
        tasks.append(asyncio.create_task(run_session(i, args, token, image)))
        if delay:
            await asyncio.sleep(delay)
    return list(await asyncio.gather(*tasks))


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    values = sorted(values)
    p90 = values[min(len(values) - 1, int(len(values) * 0.9))]
    return {
        "n": len(values),
        "median": round(statistics.median(values), 1),
        "p90": round(p90, 1),
        "max": round(values[-1], 1),
    }


def summarize(results: list[SessionResult], args: argparse.Namespace) -> dict:
    closes: dict[str, int] = {}
    for r in results:
        key = r.error or (str(r.close_code) if r.close_code is not None else "abierta")
        closes[key] = closes.get(key, 0) + 1
    seconds = max(1.0, max((r.duration_s for r in results), default=1.0))
    sent = sum(r.sent_bytes for r in results)
    recv = sum(r.recv_bytes for r in results)
    return {
        "label": args.label,
        "url_host": urlparse(args.url).hostname,
        "sessions": len(results),
        "duration_s": args.duration,
        "operator": args.operator,
        "transport": args.transport,
        "connect_ms": _stats([r.connect_ms for r in results if r.connect_ms is not None]),
        "setup_ms": _stats([r.setup_ms for r in results if r.setup_ms is not None]),
        "first_audio_ms": _stats(
            [r.first_audio_ms for r in results if r.first_audio_ms is not None]
        ),
        "closes": closes,
        "sent_kbps_per_session": round(sent * 8 / 1000 / seconds / max(1, len(results)), 1),
        "recv_kbps_per_session": round(recv * 8 / 1000 / seconds / max(1, len(results)), 1),
        "no_setup": sum(1 for r in results if r.setup_ms is None),
    }


def print_summary(summary: dict) -> None:
    print(f"\n== {summary['label'] or summary['url_host']} · {summary['sessions']} sesiones ==")
    for name in ("connect_ms", "setup_ms", "first_audio_ms"):
        s = summary[name]
        line = (
            "sin datos"
            if not s["n"]
            else f"mediana {s['median']} · p90 {s['p90']} · máx {s['max']}"
        )
        print(f"{name:>15}: {line}  (n={s['n']})")
    print(f"{'cierres':>15}: {summary['closes']}")
    print(
        f"{'tráfico/sesión':>15}: ↑ {summary['sent_kbps_per_session']} kbps · "
        f"↓ {summary['recv_kbps_per_session']} kbps"
    )
    print(f"{'sin setup':>15}: {summary['no_setup']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prueba de carga del proxy /ws/live")
    p.add_argument("url", help="wss://host/ws/live (o ws://localhost:8000/ws/live)")
    p.add_argument(
        "--sessions", type=int, default=5, help=f"sesiones simultáneas (máx. {MAX_SESSIONS})"
    )
    p.add_argument("--duration", type=float, default=30, help="segundos que dura cada sesión")
    p.add_argument("--ramp", type=float, default=0, help="segundos para ir abriendo las sesiones")
    p.add_argument("--language", default="es")
    p.add_argument("--audio-ms", type=int, default=100, help="milisegundos de audio por frame")
    p.add_argument("--image-file", help="JPEG que se envía a 1 por segundo (opcional)")
    p.add_argument("--operator", default="", help="operador a informar en start.network")
    p.add_argument("--transport", default="", choices=["", "wifi", "cellular", "other"])
    p.add_argument("--no-kickoff", action="store_true", help="no dispara el saludo [INICIO]")
    p.add_argument("--label", default="", help="nombre de la corrida (render, aws…)")
    p.add_argument("--out", help="guarda el resumen y las sesiones en este JSON")
    p.add_argument(
        "--confirm", action="store_true", help="acepta el gasto contra un servidor remoto"
    )
    args = p.parse_args(argv)
    if not 1 <= args.sessions <= MAX_SESSIONS:
        p.error(f"--sessions debe estar entre 1 y {MAX_SESSIONS}")
    if args.duration <= 0 or args.audio_ms <= 0 or args.ramp < 0:
        p.error("--duration y --audio-ms deben ser positivos y --ramp no negativo")
    host = urlparse(args.url).hostname or ""
    if host not in LOCAL_HOSTS and not args.confirm:
        p.error(
            f"{host} es un servidor remoto: cada sesión abre Gemini Live y gasta saldo. "
            "Repite con --confirm si es lo que quieres."
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(
        f"{args.sessions} sesiones de {args.duration:g} s contra "
        f"{urlparse(args.url).hostname}"
        + (f" (token de {TOKEN_ENV})" if os.environ.get(TOKEN_ENV) else " (sin token)")
    )
    results = asyncio.run(run_load(args))
    summary = summarize(results, args)
    print_summary(summary)
    if args.out:
        Path(args.out).write_text(
            json.dumps({"summary": summary, "sessions": [asdict(r) for r in results]}, indent=2),
            encoding="utf-8",
        )
        print(f"\nGuardado en {args.out}")
    return 0 if summary["no_setup"] < len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
