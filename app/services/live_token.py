"""Tokens efímeros de Gemini Live (HU-031, ADR-0003 opción B).

El backend usa la API key una vez para pedir un token de un solo uso con la
configuración de la sesión fijada (modelo, system prompt, funciones, voz): el
teléfono se conecta directo a Gemini con ese token y, aunque mande otro `setup`,
Gemini usa el del token (`lock_additional_fields=[]`). Verificado el 29-oct-2026
contra la API: un prompt distinto enviado por el cliente se ignora y el segundo
uso del token se rechaza ("Token has been used too many times").
"""

from datetime import UTC, datetime, timedelta

from google import genai

from app.core.config import settings


def setup_to_config(setup: dict) -> dict:
    """`BidiGenerateContentSetup` del proxy → `LiveConnectConfig` del SDK."""
    s = setup["setup"]
    generation = s["generation_config"]
    return {
        "response_modalities": generation["response_modalities"],
        "temperature": generation["temperature"],
        "speech_config": generation["speech_config"],
        "system_instruction": s["system_instruction"]["parts"][0]["text"],
        "tools": s["tools"],
        "proactivity": s["proactivity"],
        "realtime_input_config": s["realtime_input_config"],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
    }


def create_token(setup: dict, ttl_s: float) -> str:
    """Pide a Gemini un token de un solo uso para esta configuración.

    La sesión no puede pasar de `ttl_s`; un token sin usar vence en un minuto.
    """
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY no configurada")
    client = genai.Client(api_key=settings.gemini_api_key, http_options={"api_version": "v1alpha"})
    now = datetime.now(tz=UTC)
    token = client.auth_tokens.create(
        config={
            "uses": 1,
            "expire_time": now + timedelta(seconds=ttl_s),
            "new_session_expire_time": now + timedelta(minutes=1),
            "live_connect_constraints": {
                "model": settings.gemini_live_model,
                "config": setup_to_config(setup),
            },
            # Bloquea toda la configuración: el `setup` del teléfono no la cambia.
            "lock_additional_fields": [],
        }
    )
    return token.name
