"""Spike de HU-040 (LAZA-107): ¿avisa el asistente sin que la persona hable?

Reproduce recorridos reales de las pruebas (las fotos que guardó la app, a 1 por
segundo, como las envía la cámara) en una sesión de Gemini Live con el system
prompt de `companion.py`, y cada PERIODO segundos, si el asistente está callado,
envía el sentinela `[OBSERVA]` por el mismo flujo de la cámara (`realtime_input`;
por `client_content` el modelo no ve las fotos, ver el spike de HU-041).

Registra, por cada sentinela: la foto que se estaba mostrando, si el asistente
habló, qué dijo, la latencia hasta su primera palabra y los tokens de la sesión.

Uso (desde la raíz del backend; la API key se lee de `.env` y nunca se imprime):

    uv run python scripts/spike_observa.py FOTOS/ SALIDA.csv [PERIODO] [activas|pausa]

FOTOS/ tiene `frame_AAAAMMDD_HHMMSS_mmm.jpg`. Los recorridos se definen en
RECORRIDOS (inicio y fin por nombre de foto). Las fotos no se suben al repositorio.
"""

import asyncio
import base64
import csv
import json
import sys
import time
from pathlib import Path

import websockets

from app.services.live_service import build_setup_message, build_upstream_url

SENTINELA = "[OBSERVA]"

# La regla vive en el prompt (`_OBSERVE`, v1.13.0). Para probar una variante sin
# tocar el prompt, se puede poner aquí un texto extra que se agrega al final.
REGLA_EXTRA = ""

RECORRIDOS = {
    "casa-escalera": ("20261005_153740", "20261005_153905"),
    "parque-calle": ("20261005_160650", "20261005_160930"),
    "parqueadero-cc": ("20261005_215500", "20261005_215850"),
    "escena-quieta": ("20261005_230600", "20261005_230650"),
}


def fotos_de(carpeta: Path, inicio: str, fin: str) -> list[Path]:
    return sorted(f for f in carpeta.glob("frame_*.jpg") if inicio <= f.name[6:21] <= fin)


async def recorrer(nombre: str, fotos: list[Path], periodo: float, activas: bool) -> list[dict]:
    setup = build_setup_message("es", describing=activas)
    setup["setup"]["system_instruction"]["parts"][0]["text"] += REGLA_EXTRA
    filas: list[dict] = []
    estado = {"hablando": False, "pendiente": None, "texto": [], "tokens": 0}

    async with websockets.connect(build_upstream_url(), max_size=None) as ws:
        await ws.send(json.dumps(setup))
        while "setupComplete" not in json.loads(await ws.recv()):
            pass
        actual = {"foto": fotos[0].name}

        async def escuchar() -> None:
            async for raw in ws:
                msg = json.loads(raw)
                if u := msg.get("usageMetadata"):
                    estado["tokens"] = u.get("totalTokenCount", estado["tokens"])
                c = msg.get("serverContent", {})
                parte = c.get("outputTranscription", {}).get("text")
                if parte or c.get("modelTurn"):
                    if not estado["hablando"]:
                        estado["hablando"] = True
                        p = estado["pendiente"]
                        if p and p["latencia_s"] is None:
                            p["latencia_s"] = round(time.monotonic() - p["_t"], 2)
                    if parte:
                        estado["texto"].append(parte)
                if c.get("turnComplete"):
                    p = estado["pendiente"]
                    dicho = "".join(estado["texto"]).strip()
                    if p is not None:
                        p["dicho"] = dicho
                        p["hablo"] = int(bool(dicho))
                    elif dicho:
                        filas.append(
                            {
                                "recorrido": nombre,
                                "foto": actual["foto"],
                                "hablo": 1,
                                "dicho": dicho,
                                "latencia_s": None,
                                "sin_sentinela": 1,
                            }
                        )
                    estado.update(hablando=False, pendiente=None, texto=[])

        oyente = asyncio.create_task(escuchar())
        ultimo = time.monotonic()
        for foto in fotos:
            if oyente.done():
                # La sesión se cayó (p. ej. "service unavailable"): un silencio
                # así no es del modelo; se repite el recorrido.
                oyente.result()
                raise ConnectionError("la sesión se cerró a mitad del recorrido")
            actual["foto"] = foto.name
            b64 = base64.b64encode(foto.read_bytes()).decode()
            await ws.send(
                json.dumps(
                    {"realtime_input": {"media_chunks": [{"mime_type": "image/jpeg", "data": b64}]}}
                )
            )
            ahora = time.monotonic()
            if ahora - ultimo >= periodo and not estado["hablando"] and estado["pendiente"] is None:
                fila = {
                    "recorrido": nombre,
                    "foto": foto.name,
                    "hablo": 0,
                    "dicho": "",
                    "latencia_s": None,
                    "sin_sentinela": 0,
                    "_t": ahora,
                }
                filas.append(fila)
                estado["pendiente"] = fila
                await ws.send(json.dumps({"realtime_input": {"text": SENTINELA}}))
                ultimo = ahora
            elif estado["pendiente"] is not None and ahora - estado["pendiente"]["_t"] > 8:
                estado["pendiente"] = None  # sin respuesta: el modelo calló
            await asyncio.sleep(1.0)
        await asyncio.sleep(6)
        if oyente.done():
            oyente.result()
        oyente.cancel()
        for f in filas:
            f["tokens_sesion"] = estado["tokens"]
            f.pop("_t", None)
    return filas


async def main(fotos: str, salida: str, periodo: str = "3", modo: str = "activas") -> None:
    carpeta = Path(fotos)
    todas: list[dict] = []
    for nombre, (ini, fin) in RECORRIDOS.items():
        seq = fotos_de(carpeta, ini, fin)
        for _intento in range(4):
            try:
                filas = await recorrer(nombre, seq, float(periodo), modo == "activas")
                break
            except Exception as e:  # cierre de Gemini o red: se repite el recorrido
                print(f"{nombre}: reintento ({type(e).__name__})")
                filas = []
                await asyncio.sleep(20)
        habla = sum(f["hablo"] for f in filas if not f["sin_sentinela"])
        envios = sum(1 for f in filas if not f["sin_sentinela"])
        print(f"{nombre}: {len(seq)} fotos, {envios} sentinelas, habló en {habla}")
        for f in filas:
            if f["hablo"]:
                print(f"   {f['foto'][15:21]} ({f['latencia_s']} s) {f['dicho'][:90]}")
        todas += filas
    campos = ["recorrido", "foto", "hablo", "latencia_s", "sin_sentinela", "tokens_sesion", "dicho"]
    with open(salida, "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(todas)


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:5]))
