"""Prompt de sistema versionado del copiloto (HU-003): composición por idioma."""

import pathlib
import re

import pytest

from app.prompts import companion as c

# Regla de cierre: idioma fijo; solo cambia con pedido explícito (set_language).
LANGUAGE_CLOSING = {
    "es": "Solo cambia de idioma si la persona lo pide de forma explícita (set_language).",
    "en": "Only switch languages if the person explicitly asks (set_language).",
    "fr": "Ne change de langue que si la personne le demande explicitement (set_language).",
    "pt": "Só mude de idioma se a pessoa pedir explicitamente (set_language).",
    "it": "Cambia lingua solo se la persona lo chiede esplicitamente (set_language).",
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


def test_idioma_no_soportado_usa_espanol():
    assert c.get_live_system_prompt("de") == c.get_live_system_prompt("es")
