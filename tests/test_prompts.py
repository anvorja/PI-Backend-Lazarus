"""Prompt de sistema versionado del copiloto (HU-003): composición por idioma."""

import pathlib
import re

import pytest

from app.prompts import companion as c

# Regla de cierre: idioma fijo; solo cambia con pedido explícito a uno de los 5
# idiomas; si pide otro, no llama a set_language.
LANGUAGE_CLOSING = {
    "es": "dile en una frase que aún no está disponible y cuáles hay.",
    "en": "tell them in one sentence that it is not available yet and which ones are.",
    "fr": "dis-lui en une phrase qu'elle n'est pas encore disponible et lesquelles le sont.",
    "pt": "diga em uma frase que ainda não está disponível e quais existem.",
    "it": "dille in una frase che non è ancora disponibile e quali ci sono.",
}

# Palabra con la que empieza la regla 1 (advertencias de seguridad, P1) en cada idioma.
SAFETY_RULE = {
    "es": "1. ADVERTENCIAS DE SEGURIDAD",
    "en": "1. SAFETY WARNINGS",
    "fr": "1. AVERTISSEMENTS DE SÉCURITÉ",
    "pt": "1. AVISOS DE SEGURANÇA",
    "it": "1. AVVISI DI SICUREZZA",
}


def test_version_semantica_documentada():
    assert re.fullmatch(r"\d+\.\d+\.\d+", c.PROMPT_VERSION)
    doc = pathlib.Path(__file__).parents[1] / "docs" / "prompts" / "companion.md"
    assert f"## v{c.PROMPT_VERSION} " in doc.read_text(encoding="utf-8")


def test_los_cinco_idiomas_tienen_todas_las_partes():
    tables = [
        c._LIVE_IDENTITY,
        c._USER_NAME_KNOWN,
        c._COMMANDS_EXTRA,
        c._TASK_INTENTS,
        c._LIVE_SYSTEM_PROMPTS,
        c._VERBOSITY_DETAILED,
        c._DESCRIPTIONS_PAUSED,
        c._CAMERA_OFF,
    ]
    for table in tables:
        assert set(table) == set(c.SUPPORTED_LANGUAGES)


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_reglas_base_en_cada_idioma(language):
    prompt = c.get_live_system_prompt(language)

    assert SAFETY_RULE[language] in prompt  # P1 primero
    assert "6" in c._LIVE_SYSTEM_PROMPTS[language]  # máximo 6 palabras
    for number in range(1, 9):  # las 8 reglas numeradas
        assert re.search(rf"^{number}\. ", prompt, flags=re.M)
    assert prompt.rstrip().endswith(LANGUAGE_CLOSING[language])
    assert "[INICIO]" in prompt  # presentación única


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_orden_de_composicion(language):
    prompt = c.get_live_system_prompt(language, assistant_name="Sol")

    identity = prompt.index(c._LIVE_IDENTITY[language].format(name="Sol"))
    commands = prompt.index(c._COMMANDS_EXTRA[language])
    tasks = prompt.index(c._TASK_INTENTS[language])
    rules = prompt.index(c._LIVE_SYSTEM_PROMPTS[language])
    assert identity < commands < tasks < rules


def test_nombre_del_asistente_por_defecto_y_personalizado():
    assert c.DEFAULT_ASSISTANT_NAME in c.get_live_system_prompt("es")
    assert "Te llamas Sol" in c.get_live_system_prompt("es", assistant_name="Sol")
    assert "Te llamas Aria" in c.get_live_system_prompt("es", assistant_name="   ")


def test_nombre_de_la_persona_solo_si_lo_dijo():
    sin_nombre = c.get_live_system_prompt("es")
    con_nombre = c.get_live_system_prompt("es", user_name="Andrés")

    assert "Andrés" not in sin_nombre
    assert c._USER_NAME_KNOWN["es"].format(user_name="Andrés") in con_nombre


def test_modificadores_de_detalle_y_pausa():
    base = c.get_live_system_prompt("es")
    detallado = c.get_live_system_prompt("es", verbosity="detailed")
    pausado = c.get_live_system_prompt("es", describing=False)

    assert c._VERBOSITY_DETAILED["es"] not in base
    assert c._DESCRIPTIONS_PAUSED["es"] not in base
    assert detallado.endswith(c._VERBOSITY_DETAILED["es"])
    assert pausado.endswith(c._DESCRIPTIONS_PAUSED["es"])


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_sin_camara_avisa_solo_audio(language):
    con_camara = c.get_live_system_prompt(language)
    sin_camara = c.get_live_system_prompt(language, camera=False)

    assert c._CAMERA_OFF[language] not in con_camara
    assert sin_camara.endswith(c._CAMERA_OFF[language])
    assert "[INICIO]" in c._CAMERA_OFF[language]  # lo avisa en el saludo


def test_idioma_no_soportado_usa_espanol():
    assert c.get_live_system_prompt("de") == c.get_live_system_prompt("es")


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_confirma_un_cambio_solo_si_la_funcion_respondio_ok(language):
    # Gemini habla mientras llama a la función: debe esperar el resultado y no
    # confirmar un cambio que falló (p. ej. un idioma no soportado).
    assert "'ok'" in c._COMMANDS_EXTRA[language]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_tras_cambiar_de_idioma_confirma_sin_repetir_la_presentacion(language):
    # La app reconecta en el idioma nuevo y envía '[IDIOMA]' en lugar de '[INICIO]'.
    assert "'[IDIOMA]'" in c._LIVE_IDENTITY[language]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_saluda_por_su_nombre_a_la_persona_conocida(language):
    prompt = c.get_live_system_prompt(language, user_name="Andrés")
    assert "Andrés" in prompt
    assert "'[INICIO]'" in c._USER_NAME_KNOWN[language]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_cada_ajuste_por_voz_nombra_su_funcion(language):
    # En la prueba el asistente dijo que cambió el detalle sin llamar a la función.
    identity = c._LIVE_IDENTITY[language]
    for function in (
        "set_assistant_name",
        "set_user_name",
        "set_voice",
        "set_language",
        "set_verbosity",
        "set_system_cues",
        "set_descriptions",
    ):
        assert function in identity


# HU-010: la ayuda nombra las tareas a petición (leer, describir, buscar).
HELP_TASKS = {
    "es": ("leer un texto", "describir dónde está", "buscar un objeto"),
    "en": ("read a text", "describe where they are", "find an object"),
    "fr": ("lire un texte", "décrire où elle se trouve", "chercher un objet"),
    "pt": ("ler um texto", "descrever onde está", "procurar um objeto"),
    "it": ("leggere un testo", "descrivere dove si trova", "cercare un oggetto"),
}

# HU-010: repetir es literal y la pausa mantiene la regla 1 (advertencias).
REPEAT_SAME_WORDS = {
    "es": "con las mismas palabras",
    "en": "with the same words",
    "fr": "avec les mêmes mots",
    "pt": "com as mesmas palavras",
    "it": "con le stesse parole",
}
RULE_1 = {"es": "regla 1", "en": "rule 1", "fr": "règle 1", "pt": "regra 1", "it": "regola 1"}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_la_ayuda_incluye_las_tareas_a_peticion(language):
    for task in HELP_TASKS[language]:
        assert task in c._COMMANDS_EXTRA[language]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_repetir_repite_la_ultima_respuesta_tal_cual(language):
    assert REPEAT_SAME_WORDS[language] in c._COMMANDS_EXTRA[language]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_en_pausa_mantiene_las_advertencias_de_seguridad(language):
    # Pausa pedida en mitad de la sesión: el modificador aún no está en el prompt.
    assert RULE_1[language] in c._COMMANDS_EXTRA[language]
    # Sesión que arranca en pausa: lo avisa al saludar.
    assert "'[INICIO]'" in c._DESCRIPTIONS_PAUSED[language]
    paused = c.get_live_system_prompt(language, describing=False)
    assert paused.endswith(c._DESCRIPTIONS_PAUSED[language])


ALWAYS = {"es": "SIEMPRE", "en": "ALWAYS", "fr": "TOUJOURS", "pt": "SEMPRE", "it": "SEMPRE"}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_buscar_un_objeto_que_no_esta_sugiere_girar(language):
    # En la prueba dijo "No veo ninguna bicicleta" sin sugerir girar el teléfono.
    assert ALWAYS[language] in c._TASK_INTENTS[language]
