"""Spike de HU-041 (LAZA-109): ¿acierta el asistente izquierda y derecha?

Le pregunta al mismo modelo de producción (Gemini Live, con el system prompt de
`companion.py`) de qué lado está un objeto en fotos reales de las pruebas, con
cuatro variantes:

  A  prompt actual y foto tal cual (línea base)
  B  prompt con el marco de referencia reforzado
  C  foto con franjas IZQ / DER en los bordes (más una línea que las explica)
  D  B + C
  E  como en la app: la foto en el flujo de la cámara y la pregunta en el mismo flujo
  F  E con la imagen en resolución alta (`media_resolution`)
  G  E preguntando "¿… está a la derecha o a la izquierda?"
  H  E preguntando "¿… está a la izquierda o a la derecha?"

Uso (desde la raíz del backend; la API key se lee de `.env` y nunca se imprime):

    uv run python scripts/spike_lateralidad.py DATASET.csv FOTOS/ MARCAS/ SALIDA.csv [ABCDEF]

DATASET.csv tiene las columnas `foto,objeto,lado` (lado: izquierda, derecha o
frente). FOTOS/ y MARCAS/ tienen `frame_20261005_<foto>.jpg` sin y con franjas.
Las fotos no se suben al repositorio.
"""

import asyncio
import base64
import csv
import json
import re
import sys
from pathlib import Path

import websockets

from app.services.live_service import build_setup_message, build_upstream_url

REFUERZO = (
    "\nMARCO DE REFERENCIA (izquierda y derecha): la imagen es lo que la persona "
    "tiene delante; la cámara trasera apunta hacia adelante y la imagen NO es un "
    "espejo. Lo que aparece en la mitad izquierda de la imagen está a su "
    "IZQUIERDA y lo de la mitad derecha, a su DERECHA. Antes de decir un lado, "
    "ubica el objeto en la imagen. Si está cerca del centro, di 'al frente'. Las "
    "horas del reloj van con el lado: de 1 a 5 es derecha y de 7 a 11 es izquierda."
)
MARCAS = (
    "\nLas franjas IZQ y DER de los bordes de la imagen las pone la aplicación: "
    "marcan la izquierda y la derecha de la persona. Úsalas para decir el lado y "
    "no las menciones."
)
# (texto extra del prompt, foto con franjas, modo de envío, resolución de la imagen)
#   turno: la foto va en el mismo turno que la pregunta.
#   vivo:  como en la app, la foto en el flujo de la cámara (1 por segundo) y la
#          pregunta en el mismo flujo (`realtime_input`).
VARIANTES = {
    "A": ("", False, "turno", None),
    "B": (REFUERZO, False, "turno", None),
    "C": (MARCAS, True, "turno", None),
    "D": (REFUERZO + MARCAS, True, "turno", None),
    "E": ("", False, "vivo", None),
    "F": ("", False, "vivo", "MEDIA_RESOLUTION_HIGH"),
    "G": ("", False, "vivo", None),
    "H": ("", False, "vivo", None),
}
# En el teléfono la persona suele dar las dos opciones ("¿está a la derecha o a la
# izquierda?"); G y H miden si el modelo se inclina por la última que oyó.
PREGUNTAS = {
    "G": "¿{objeto} está a la derecha o a la izquierda?",
    "H": "¿{objeto} está a la izquierda o a la derecha?",
}


_HORAS = {
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
}


def lado_de(respuesta: str) -> str:
    """Primer lado que menciona la respuesta (palabra u hora del reloj)."""
    texto = respuesta.lower()
    candidatos = []
    for palabra, lado in (
        ("izquierd", "izquierda"),
        ("derech", "derecha"),
        ("al frente", "frente"),
        ("enfrente", "frente"),
        ("delante", "frente"),
        ("centro", "frente"),
    ):
        i = texto.find(palabra)
        if i >= 0:
            candidatos.append((i, lado))
    for m in re.finditer(r"a (?:las|la) (\d{1,2}|" + "|".join(_HORAS) + r")\b", texto):
        hora = int(m.group(1)) if m.group(1).isdigit() else _HORAS[m.group(1)]
        lado = "frente" if hora in (12, 6) else ("derecha" if 1 <= hora <= 5 else "izquierda")
        candidatos.append((m.start(), lado))
    return min(candidatos)[1] if candidatos else "sin lado"


async def preguntar(
    foto: bytes, pregunta: str, extra: str, modo: str = "turno", resolucion: str | None = None
) -> str:
    setup = build_setup_message("es")
    setup["setup"]["system_instruction"]["parts"][0]["text"] += extra
    if resolucion:
        setup["setup"]["generation_config"]["media_resolution"] = resolucion
    async with websockets.connect(build_upstream_url(), max_size=None) as ws:
        await ws.send(json.dumps(setup))
        while "setupComplete" not in json.loads(await ws.recv()):
            pass
        b64 = base64.b64encode(foto).decode()
        if modo == "vivo":
            for _ in range(3):
                await ws.send(
                    json.dumps(
                        {
                            "realtime_input": {
                                "media_chunks": [{"mime_type": "image/jpeg", "data": b64}]
                            }
                        }
                    )
                )
                await asyncio.sleep(1.0)
            await ws.send(json.dumps({"realtime_input": {"text": pregunta}}))
        else:
            # Con la foto en el flujo y la pregunta como `client_content`, el
            # modelo no toma la foto: respondía describiendo escenas inventadas.
            await ws.send(
                json.dumps(
                    {
                        "client_content": {
                            "turns": [
                                {
                                    "role": "user",
                                    "parts": [
                                        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                                        {"text": pregunta},
                                    ],
                                }
                            ],
                            "turn_complete": True,
                        }
                    }
                )
            )
        dicho = []
        async with asyncio.timeout(40):
            while True:
                msg = json.loads(await ws.recv())
                content = msg.get("serverContent", {})
                if t := content.get("outputTranscription", {}).get("text"):
                    dicho.append(t)
                if content.get("turnComplete"):
                    return "".join(dicho).strip()


async def main(dataset: str, fotos: str, marcas: str, salida: str, cuales: str = "ABCDEF") -> None:
    filas = list(csv.DictReader(open(dataset, encoding="utf-8")))
    sem = asyncio.Semaphore(4)
    resultados = []

    async def uno(fila: dict, variante: str) -> None:
        extra, con_marcas, modo, resolucion = VARIANTES[variante]
        carpeta = Path(marcas if con_marcas else fotos)
        foto = (carpeta / f"frame_20261005_{fila['foto']}.jpg").read_bytes()
        plantilla = PREGUNTAS.get(variante, "¿De qué lado está {objeto}?")
        objeto = fila["objeto"]
        pregunta = plantilla.format(
            objeto=objeto[0].upper() + objeto[1:] if plantilla[1] == "{" else objeto
        )
        async with sem:
            for intento in range(3):
                try:
                    respuesta = await preguntar(foto, pregunta, extra, modo, resolucion)
                    break
                except Exception as e:  # red o cierre de Gemini: se reintenta
                    respuesta = f"ERROR {type(e).__name__}"
                    await asyncio.sleep(2 + intento * 3)
        lado = lado_de(respuesta)
        resultados.append(
            {
                "variante": variante,
                **fila,
                "dicho": lado,
                "acierto": int(lado == fila["lado"]),
                "respuesta": respuesta,
            }
        )
        print(f"{variante} {fila['foto']} {fila['lado']:>9} → {lado:<9} {respuesta[:70]}")

    await asyncio.gather(*(uno(f, v) for v in cuales for f in filas))
    with open(salida, "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=list(resultados[0]))
        w.writeheader()
        w.writerows(sorted(resultados, key=lambda r: (r["variante"], r["foto"])))
    for v in cuales:
        rs = [r for r in resultados if r["variante"] == v]
        print(f"Variante {v}: {sum(r['acierto'] for r in rs)}/{len(rs)}")


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:6]))
