"""Helpers para la sesión Gemini Live (audio nativo) sobre la Developer API.

El backend actúa como proxy WebSocket (ver `app/sockets/live_proxy.py`): la
app móvil habla con este backend y el backend habla con Gemini. La API key viaja
solo aquí (query param), nunca llega al cliente.

A diferencia de Vertex AI, la Developer API:
- usa la API key en la URL (`?key=...`), sin Bearer ni ADC;
- el `setup.model` es `models/<MODEL>` (sin `projects/.../locations/...`).
"""

from urllib.parse import quote

from app.core.config import settings
from app.prompts.companion import get_live_system_prompt


def build_upstream_url() -> str:
    """URL del WebSocket de Gemini Live con la API key como query param."""
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY no configurada. Defínela en .env para usar /ws/live.")
    return f"{settings.gemini_live_url}?key={quote(settings.gemini_api_key)}"


# Tools que la persona puede invocar por voz (personalización persistente).
# Gemini emite un toolCall; la app lo ejecuta (persiste el ajuste) y responde.
_FUNCTION_DECLARATIONS = [
    {
        "name": "set_assistant_name",
        "description": (
            "Cambia el nombre con el que el asistente se identifica "
            "(p. ej. 'Lazarus'). Úsalo cuando la persona pida llamarte de otra "
            "forma. The new name persists across sessions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nuevo nombre del asistente.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "set_user_name",
        "description": (
            "Guarda el nombre de la PERSONA usuaria (no el del asistente). Úsalo "
            "cuando la persona diga cómo se llama ('me llamo Andrés', 'yo soy "
            "Andrés'). Persiste entre sesiones."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nombre de la persona usuaria.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "set_voice",
        "description": (
            "Cambia la VOZ con la que habla el asistente (timbre), distinta del "
            "nombre. Úsalo cuando la persona pida cambiar tu voz o probar otra. Al "
            "cambiarla, la sesión se reinicia y la persona oye la nueva voz al "
            "instante. Persiste entre sesiones."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "voice": {
                    "type": "string",
                    "enum": [
                        "Charon",
                        "Puck",
                        "Kore",
                        "Fenrir",
                        "Aoede",
                        "Leda",
                        "Orus",
                        "Zephyr",
                    ],
                    "description": "Nombre de la voz prebuilt elegida.",
                },
            },
            "required": ["voice"],
        },
    },
    {
        "name": "set_language",
        "description": (
            "Cambia el idioma de la conversación. Úsalo cuando la persona pida "
            "hablar en otro idioma. Persiste entre sesiones."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "enum": ["es", "en", "fr", "pt", "it"],
                    "description": "Código ISO del idioma destino.",
                },
            },
            "required": ["language"],
        },
    },
    {
        "name": "set_verbosity",
        "description": (
            "Ajusta cuánto detalle dan las descripciones. 'concise' = frases muy "
            "cortas; 'detailed' = algo más de contexto. Persiste."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "description": "Nivel de detalle deseado.",
                },
            },
            "required": ["level"],
        },
    },
    {
        "name": "set_descriptions",
        "description": (
            "Activa o pausa las descripciones automáticas del entorno. Cuando está "
            "en pausa solo respondes preguntas y alertas de seguridad. Persiste."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "True para describir el entorno; False para pausar.",
                },
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "set_system_cues",
        "description": (
            "Silencia o activa los sonidos de aviso de la aplicación (earcons de "
            "conexión/error). Útil si la persona usa lector de pantalla. Persiste."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "True para activar los avisos; False para silenciarlos.",
                },
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "set_meeting_mode",
        "description": (
            "Activa o desactiva el MODO REUNIÓN. Úsalo cuando la persona diga que "
            "está en una reunión, clase o conversación y quiera que escuches y "
            "recuerdes lo que se dice pero SIN hablar, salvo que te llame por tu "
            "nombre. Con enabled=True entras en modo reunión (callado y atento); "
            "con enabled=False sales y vuelves al modo normal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": (
                        "True para entrar en modo reunión (silencioso, atento); False para salir."
                    ),
                },
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "set_microphone",
        "description": (
            "Enciende o apaga el MICRÓFONO, para silencio total y privacidad. Úsalo "
            "cuando la persona pida silencio total, que no escuches nada o que te "
            "apagues. Con active=False la app deja de enviar audio y vídeo: no oyes "
            "ni recuerdas nada hasta que la persona te reactive TOCANDO LA PANTALLA "
            "(no por voz, porque el micrófono estará apagado). Antes de apagarlo, "
            "avísale en una frase corta de que toque la pantalla para reactivarte."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "active": {
                    "type": "boolean",
                    "description": (
                        "False para apagar el micrófono (silencio total); True para reactivarlo."
                    ),
                },
            },
            "required": ["active"],
        },
    },
]


def build_setup_message(
    language: str = "es",
    voice: str | None = None,
    assistant_name: str | None = None,
    user_name: str | None = None,
    verbosity: str = "concise",
    describing: bool = True,
    camera: bool = True,
) -> dict:
    """Construye el primer mensaje `setup` (BidiGenerateContentSetup) para Gemini.

    El system prompt vive server-side (`companion.py`) como única fuente de
    verdad; la app solo elige idioma, voz, nombre y preferencias de
    verbosidad/descripción (personalizables por voz, persistentes).
    """
    voice_name = voice or settings.gemini_live_voice
    system_prompt = get_live_system_prompt(
        language,
        assistant_name,
        user_name=user_name,
        verbosity=verbosity,
        describing=describing,
        camera=camera,
    )

    return {
        "setup": {
            "model": f"models/{settings.gemini_live_model}",
            "generation_config": {
                "response_modalities": ["AUDIO"],
                "temperature": 0.3,
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": voice_name},
                    },
                },
            },
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "tools": [{"function_declarations": _FUNCTION_DECLARATIONS}],
            # Proactividad: Gemini puede hablar sin esperar al usuario (describe
            # el entorno por su cuenta). Interrumpible por defecto.
            "proactivity": {"proactive_audio": True},
            # Detección automática de voz: cuando la persona empieza a hablar, el
            # asistente se interrumpe (barge-in).
            "realtime_input_config": {
                "automatic_activity_detection": {"disabled": False},
                "activity_handling": "START_OF_ACTIVITY_INTERRUPTS",
            },
            # Transcripción de la voz del usuario y del asistente: la app las
            # registra en su log como evidencia de lo que se dijo en cada turno.
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }
    }
