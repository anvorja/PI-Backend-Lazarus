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
        c._SOS,
        c._OBSERVE,
        c._SCREEN_LOCKED,
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
        "set_meeting_mode",
        "set_microphone",
        "get_location",
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


SUMMARY = {"es": "resume", "en": "summarize", "fr": "résume", "pt": "resuma", "it": "riassumi"}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_en_modo_reunion_resume_lo_escuchado(language):
    assert SUMMARY[language] in c._COMMANDS_EXTRA[language]


# HU-012: la alerta SOS nombra sus funciones, sigue el resultado de la app y
# recuerda la línea oficial 123.
SOS_FUNCTIONS = ("trigger_sos", "cancel_sos", "set_emergency_contact", "call_phone")
SOS_RESULTS = ("'pending'", "'sent'", "'unconfirmed'", "'failed'", "'no_contact'")


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_sos_nombra_sus_funciones_y_resultados(language):
    sos = c._SOS[language]
    for name in SOS_FUNCTIONS + SOS_RESULTS:
        assert name in sos
    assert "[SOS]" in sos  # alerta enviada por la app sin confirmación
    assert "123" in sos


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_sos_va_tras_los_comandos_y_antes_de_las_tareas(language):
    prompt = c.get_live_system_prompt(language)
    commands = prompt.index(c._COMMANDS_EXTRA[language])
    sos = prompt.index(c._SOS[language])
    tasks = prompt.index(c._TASK_INTENTS[language])
    assert commands < sos < tasks


# HU-012: un SOS nuevo siempre pasa por la app, que decide si pregunta por otra
# alerta (en la prueba el modelo se negó por su cuenta a enviar una segunda).
SOS_ALWAYS = {
    "es": "aunque ya hayas enviado una",
    "en": "even if an alert was already sent",
    "fr": "même si une alerte a déjà été envoyée",
    "pt": "mesmo que um alerta já tenha sido enviado",
    "it": "anche se un avviso è già stato inviato",
}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_cada_sos_llama_a_la_funcion_aunque_ya_se_haya_enviado(language):
    assert SOS_ALWAYS[language] in " ".join(c._SOS[language].split())


WHERE_AM_I = {
    "es": "dónde estoy",
    "en": "where am i",
    "fr": "où suis-je",
    "pt": "onde estou",
    "it": "dove sono",
}
LOCATION_EVERY_TIME = {
    "es": "cada vez",
    "en": "every time",
    "fr": "à chaque fois",
    "pt": "toda vez",
    "it": "ogni volta",
}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_donde_estoy_pide_la_ubicacion_cada_vez(language):
    # En la prueba de CP-LAZA-39, bajo techo respondió "¿dónde estoy?" con la
    # descripción de la sala (la tarea de escena) sin llamar a get_location.
    assert WHERE_AM_I[language] not in c._TASK_INTENTS[language].lower()
    assert LOCATION_EVERY_TIME[language] in c._LIVE_IDENTITY[language]


# HU-041: los lados se dicen según la imagen más reciente y se corrigen en voz
# alta (en el spike, viendo la foto, acertó el 98 %; la confusión venía de la
# conversación en vivo).
SIDES_RECENT = {
    "es": "MÁS RECIENTE",
    "en": "MOST RECENT",
    "fr": "LA PLUS RÉCENTE",
    "pt": "MAIS RECENTE",
    "it": "PIÙ RECENTE",
}
SIDES_CORRECT = {
    "es": "Corrijo",
    "en": "Correction",
    "fr": "Je corrige",
    "pt": "Corrijo",
    "it": "Correggo",
}


# En CP-LAZA-109 el asistente aceptó cada corrección de la persona sin mirar.
SIDES_CHECK = {
    "es": "solo si la imagen lo confirma",
    "en": "only if the image confirms it",
    "fr": "seulement si l'image le confirme",
    "pt": "só se a imagem confirmar",
    "it": "solo se l'immagine lo conferma",
}


# En CP-LAZA-109, tras "no veo un piano" dos veces, a la tercera pregunta dijo
# "mueble similar a un piano, a la derecha" (estaba a la izquierda).
NOT_SEEN = {
    "es": "aunque te lo pregunten varias veces",
    "en": "even if they ask several times",
    "fr": "même si on te le demande plusieurs fois",
    "pt": "mesmo que perguntem várias vezes",
    "it": "anche se te lo chiedono più volte",
}


# En CP-LAZA-109 respondió "Señora, a tu izquierda" cuando ya no estaba en la
# imagen, y aceptó "está a la derecha" sin verla.
LAST_SEEN = {
    "es": "ahora no lo veo",
    "en": "I do not see it now",
    "fr": "je ne le vois plus",
    "pt": "agora não o vejo",
    "it": "ora non lo vedo",
}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_lo_que_ya_no_ve_lo_dice_y_no_acepta_correcciones_sin_verlo(language):
    assert LAST_SEEN[language] in " ".join(c._TASK_INTENTS[language].split())


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_si_no_reconoce_el_objeto_no_lo_inventa_aunque_insistan(language):
    assert NOT_SEEN[language] in " ".join(c._TASK_INTENTS[language].split())


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_una_correccion_de_la_persona_se_comprueba_en_la_imagen(language):
    assert SIDES_CHECK[language] in " ".join(c._TASK_INTENTS[language].split())


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_los_lados_salen_de_la_imagen_mas_reciente_y_se_corrigen(language):
    tasks = c._TASK_INTENTS[language]
    assert SIDES_RECENT[language] in tasks
    assert SIDES_CORRECT[language] in tasks


# HU-040: ciclo de observación. El asistente atiende '[OBSERVA]' en los 5 idiomas,
# habla solo ante un riesgo o algo nuevo, y en pausa solo ante un riesgo.
SAY_NOTHING = {
    "es": "NO DIGAS NADA",
    "en": "SAY NOTHING",
    "fr": "NE DIS RIEN",
    "pt": "NÃO DIGA NADA",
    "it": "NON DIRE NULLA",
}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_observa_avisa_solo_de_riesgos_o_algo_nuevo(language):
    observe = c._OBSERVE[language]
    assert "'[OBSERVA]'" in observe
    assert SAY_NOTHING[language] in observe
    assert " 8 " in " ".join(observe.split())  # lo nuevo, en 8 palabras como máximo
    # En pausa la app envía '[OBSERVA_RIESGOS]' (el modelo olvidaba la pausa).
    assert "'[OBSERVA_RIESGOS]'" in observe
    assert observe in c.get_live_system_prompt(language)


# Prueba con TalkBack del 27-oct: con la persona quieta, el asistente dijo cada 6 s
# "Vista similar, los auriculares siguen sobre la cartera", "Solo veo una parte de tu
# brazo" y volvió a ubicar los mismos auriculares, encima de la voz de TalkBack.
SAME_VIEW = {
    "es": "'vista similar'",
    "en": "'similar view'",
    "fr": "« vue similaire »",
    "pt": "'vista semelhante'",
    "it": "'vista simile'",
}
ONLY_SEE = {
    "es": "'solo veo…'",
    "en": "'I only see…'",
    "fr": "« je ne vois que… »",
    "pt": "'só vejo…'",
    "it": "'vedo solo…'",
}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_observa_no_dice_que_sigue_igual_ni_repite_objetos(language):
    observe = " ".join(c._OBSERVE[language].split())
    assert SAME_VIEW[language] in observe
    assert ONLY_SEE[language] in observe


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_en_pausa_observa_solo_por_riesgos(language):
    assert "'[OBSERVA]'" in c._DESCRIPTIONS_PAUSED[language]


# Lo que dice el asistente al bloquear y al desbloquear la pantalla (HU-017).
SCREEN_LOCKED_SAYS = {
    "es": ("'Sigo contigo, pero sin ver.'", "'Vuelvo a ver.'"),
    "en": ("'I'm still with you, but I can't see.'", "'I can see again.'"),
    "fr": ("'Je suis toujours là, mais je ne vois plus.'", "'Je vois de nouveau.'"),
    "pt": ("'Continuo com você, mas sem ver.'", "'Voltei a ver.'"),
    "it": ("'Sono ancora con te, ma non vedo.'", "'Vedo di nuovo.'"),
}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_pantalla_bloqueada_avisa_que_sigue_sin_ver(language):
    locked = c._SCREEN_LOCKED[language]
    off, on = SCREEN_LOCKED_SAYS[language]
    assert "'[SIN_CAMARA]'" in locked and off in locked
    assert "'[CAMARA]'" in locked and on in locked
    # Va junto a la observación, siempre (la pantalla se bloquea en cualquier sesión).
    prompt = c.get_live_system_prompt(language)
    assert prompt.index(c._OBSERVE[language]) < prompt.index(locked)


# Lo que inventó en la caminata de CP-LAZA-45 con la pantalla bloqueada.
INVENTED = {
    "es": ("obstáculos", "por dónde caminar"),
    "en": ("obstacles", "which way to walk"),
    "fr": ("obstacles", "par où marcher"),
    "pt": ("obstáculos", "por onde andar"),
    "it": ("ostacoli", "dove camminare"),
}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_pantalla_bloqueada_prohibe_decir_las_marcas(language):
    # En la caminata dijo "[CAMARA] Vuelvo a ver." sin que la app lo enviara.
    locked = c._SCREEN_LOCKED[language]
    assert "'[CAMARA]'" in locked
    assert locked.count("'[CAMARA]'") >= 3  # quién lo envía, qué decir, cuándo no


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_sesion_con_pantalla_bloqueada_no_describe_y_si_da_la_ubicacion(language):
    base = c.get_live_system_prompt(language)
    blind = c.get_live_system_prompt(language, screen_locked=True)
    block = c._SCREEN_LOCKED_SESSION[language]

    assert block not in base
    assert blind.endswith(block)
    for word in INVENTED[language]:
        assert word in block
    # Después de reconectarse se negó a dar la ubicación "porque la cámara está
    # bloqueada": el GPS no depende de la cámara.
    assert "get_location" in block and "GPS" in block
    # Sin imágenes no hay ciclo de observación (la app no envía '[OBSERVA]').
    assert c._OBSERVE[language] not in blind
    assert c._SCREEN_LOCKED[language] in blind  # '[SIN_CAMARA]' sigue siendo el saludo


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_sin_permiso_de_camara_manda_el_modo_solo_audio(language):
    prompt = c.get_live_system_prompt(language, camera=False, screen_locked=True)
    assert prompt.endswith(c._CAMERA_OFF[language])
    assert c._SCREEN_LOCKED_SESSION[language] not in prompt


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("screen_locked", [False, True])
def test_sin_rutas_no_inventa_como_llegar(language, screen_locked):
    # En la caminata inventó giros hacia una dirección y dijo que ya había llegado.
    prompt = c.get_live_system_prompt(language, screen_locked=screen_locked)
    rule = c._NO_ROUTES[language]
    assert rule in prompt
    assert "get_location" in rule


def test_el_setup_lleva_la_sesion_sin_imagenes():
    from app.services.live_service import build_setup_message

    setup = build_setup_message("es", screen_locked=True)
    text = setup["setup"]["system_instruction"]["parts"][0]["text"]
    assert text.endswith(c._SCREEN_LOCKED_SESSION["es"])


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("screen_locked", [False, True])
def test_la_hora_la_da_el_telefono(language, screen_locked):
    # LAZA-115: dijo "Son las 4:58 de la tarde UTC" a las 11:58 de Colombia.
    prompt = c.get_live_system_prompt(language, screen_locked=screen_locked)
    rule = c._TIME[language]
    assert rule in prompt
    assert "get_time" in rule
    assert "UTC" in rule  # para prohibir decirla


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("screen_locked", [False, True])
def test_la_orientacion_la_da_la_brujula(language, screen_locked):
    # HU-016: hacia dónde mira, con get_heading; descalibrada, pide el ocho.
    prompt = c.get_live_system_prompt(language, screen_locked=screen_locked)
    rule = c._HEADING[language]
    assert rule in prompt
    assert "get_heading" in rule
    assert "needs_calibration" in rule


COMPASS_WORD = {
    "es": "'brújula'",
    "en": "'compass'",
    "fr": "'boussole'",
    "pt": "'bússola'",
    "it": "'bussola'",
}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_brujula_es_el_comando_y_la_ayuda_lo_ensena(language):
    # HU-016: "¿Hacia dónde voy?" se contestó por la cámara; la palabra clave es
    # "brújula", y la ayuda la menciona.
    word = COMPASS_WORD[language]
    assert word in c._HEADING[language]
    help_start = c._COMMANDS_EXTRA[language].index(
        {"es": "AYUDA", "en": "HELP", "fr": "AIDE", "pt": "AJUDA", "it": "AIUTO"}[language]
    )
    assert word in c._COMMANDS_EXTRA[language][help_start:]


def test_en_espanol_dice_oriente_y_occidente():
    rule = c._HEADING["es"]
    assert "oriente y occidente" in rule
    assert "Miras al norte." in rule and "Vas hacia el norte." in rule


NOTE_WORD = {
    "es": "'anota que…'",
    "en": "'note that…'",
    "fr": "'note que…'",
    "pt": "'anota que…'",
    "it": "'annota che…'",
}


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("screen_locked", [False, True])
def test_anota_que_guarda_la_nota_y_la_ayuda_lo_ensena(language, screen_locked):
    # HU-024, criterio 3: la nota queda con hora y posición (add_note).
    prompt = c.get_live_system_prompt(language, screen_locked=screen_locked)
    rule = c._NOTES[language]
    assert rule in prompt
    assert "add_note" in rule
    help_word = {"es": "AYUDA", "en": "HELP", "fr": "AIDE", "pt": "AJUDA", "it": "AIUTO"}
    extra = c._COMMANDS_EXTRA[language]
    assert NOTE_WORD[language] in extra[extra.index(help_word[language]) :]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("screen_locked", [False, True])
def test_unicentro_consulta_la_regla_de_la_app(language, screen_locked):
    # HU-019: la Ruta A por Unicentro se decide en la app (regla 5) y el aviso
    # '[UNICENTRO]' lo envía la app cuando se desactiva durante la sesión (regla 3).
    prompt = c.get_live_system_prompt(language, screen_locked=screen_locked)
    rule = c._UNICENTRO[language]
    assert rule in prompt
    assert "get_unicentro_route" in rule
    assert "'unavailable'" in rule
    assert "[UNICENTRO]" in rule
    # Regla 6: con tropel la Ruta A se cierra todo el día, y se levanta por voz.
    assert "set_route_disturbance" in rule
    assert "tropel" in rule
    assert "active=true" in rule and "active=false" in rule
    # Levantarlo pide doble confirmación: la app responde 'pending' la primera vez.
    assert "'pending'" in rule
    # La alternativa es otra portería, no "ir por la calle".
    assert "Calle 16" in rule and "Carrera 86" in rule
    # Remite al bloque sin rutas con su mismo nombre.
    no_routes = c._NO_ROUTES[language].split(":")[0].strip()
    assert no_routes in rule


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("screen_locked", [False, True])
def test_las_funciones_no_se_narran(language, screen_locked):
    # En el teléfono el asistente decía "Llamando a la función…" y "Consultando
    # si…" antes de cada función: son internas y la persona no debe oírlas.
    prompt = c.get_live_system_prompt(language, screen_locked=screen_locked)
    rule = c._SILENT_TOOLS[language]
    assert rule in prompt
    # Va justo después de la identidad, antes de las demás reglas.
    assert prompt.index(rule) < prompt.index(c._COMMANDS_EXTRA[language])
    assert "'pending'" in rule and "'unavailable'" in rule


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_con_talkback_los_gestos_son_tocar_dos_veces(language):
    # HU-023: con TalkBack un toque solo enfoca; la app avisa al iniciar.
    rule = c._SCREEN_READER[language]
    assert rule in c.get_live_system_prompt(language, screen_reader=True)
    assert rule not in c.get_live_system_prompt(language)
    # También en la sesión abierta con la pantalla bloqueada.
    assert rule in c.get_live_system_prompt(language, screen_locked=True, screen_reader=True)
    assert "TalkBack" in rule
    # Su voz llega por el micrófono: no es la persona y nunca dispara el SOS.
    assert "trigger_sos" in rule


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("screen_locked", [False, True])
def test_campo_cruces_notas_y_rutas(language, screen_locked):
    # Fase 0 (17 de octubre): el asistente autorizó cruces ("puedes cruzar"), dijo
    # "Anotado." sin llamar a add_note y eligió el camino ("puedes ir por ahí").
    prompt = c.get_live_system_prompt(language, screen_locked=screen_locked)
    assert c._CROSSING[language] in prompt
    assert "add_note" in c._NOTES[language] and "'ok'" in c._NOTES[language]
    assert "guide me" in c._NO_ROUTES["en"]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_anotar_no_consulta_ubicacion_rumbo_ni_hora(language):
    # Jornada del 24 de octubre: con "posición, brújula, fecha y hora, anota…" el
    # asistente llamaba a get_location, get_heading y get_time antes de add_note (9–15 s).
    # La nota ya guarda esos datos.
    rule = c._NOTES[language]
    for tool in ("get_location", "get_heading", "get_time"):
        assert tool in rule


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_campo_direccion_solo_con_get_location(language):
    # Participante 2: "Ahora mismo estás en la Carrera 82" sin llamar a get_location
    # (estaba en la Carrera 100); y "Te avisaré cuando esté en verde para cruzar".
    assert c._NO_ROUTES[language].count("get_location") >= 2
    assert "danger" in c._CROSSING["en"] and "promise" in c._CROSSING["en"]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_campo_cruces_al_principio_y_con_las_frases_exactas(language):
    # Participante 3: aún dijo "puedes cruzar con precaución" y "no hay peligro de
    # cruzar". La regla va justo después de FUNCIONES EN SILENCIO.
    prompt = c.get_live_system_prompt(language)
    rule = c._CROSSING[language]
    assert prompt.index(rule) < prompt.index(c._COMMANDS_EXTRA[language])
    assert "puedes cruzar con precaución" in c._CROSSING["es"]
    assert "no hay peligro" in c._CROSSING["es"]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_campo_no_narra_varias_funciones(language):
    # Participante 3: "Ahora consulto la ubicación, la hora y la brújula".
    rule = c._SILENT_TOOLS[language]
    assert "consult" in rule or "check" in rule


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_cruce_con_semaforo_apagado_o_dudoso(language):
    # HU-020 (LAZA-48): con un semáforo sin luces dice que no ve ninguna luz y que no
    # se guíe por él; a "¿puedo cruzar?" no lo confirma; ante un bloqueo ofrece el SOS.
    rule = c._CROSSING[language]
    assert "SOS" in rule
    assert "SOS" in c.get_live_system_prompt(language, screen_locked=True)
    assert "no veo ninguna luz" in c._CROSSING["es"]
    assert "no puedes confirmarlo" in c._CROSSING["es"]
    assert "cannot confirm" in c._CROSSING["en"]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("screen_locked", [False, True])
def test_ruta_con_gps_perdido_no_afirma_la_posicion(language, screen_locked):
    # HU-021 fase 1 (LAZA-49): la app avisa 'gps lost' y 'gps back'; mientras tanto el
    # asistente no dice en qué punto va ni dónde está.
    rule = c._ROUTE[language]
    assert "'gps lost'" in rule and "'gps back'" in rule
    # Fase 2: estimación con los pasos y, a los 3 minutos, ayuda o SOS.
    assert "get_route_progress" in rule and "'gps still lost'" in rule
    assert "SOS" in rule
    assert rule in c.get_live_system_prompt(language, screen_locked=screen_locked)
    assert "nunca digas en qué punto va" in c._ROUTE["es"]
    assert "never say which point" in c._ROUTE["en"]


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_cruce_con_las_heuristicas_de_orientacion_y_movilidad(language):
    # HU-020, estado del arte (29-oct): semáforo peatonal vs. vehicular, giro a la
    # derecha en rojo (Ley 769, art. 118), cebra como cruce sin control, silencio
    # mientras cruza y la llegada la confirma el bastón.
    rule = c._CROSSING[language]
    assert any(n in rule for n in ("Colombia", "Colombie", "Colômbia"))
    assert rule in c.get_live_system_prompt(language)
    es = c._CROSSING["es"]
    for phrase in (
        "no veo semáforo peatonal",
        "girar a la derecha en rojo",
        "los conductores no siempre ceden",
        "habla lo mínimo",
        "confirme con el bastón",
    ):
        assert phrase in es
