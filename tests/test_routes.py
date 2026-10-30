"""HU-022: perfiles de ruta curados en la base de datos, el panel y la app.

Las coordenadas de estas pruebas son ficticias (cerca de 0,0): las reales no van
en el repositorio.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.prompts import companion as c
from app.schemas.route_profile import RouteProfile
from app.services.live_service import _FUNCTION_DECLARATIONS
from tests.test_access import _admin, _register, _set_device


def _profile(slug: str = "estacion-prueba-ida", **fields) -> dict:
    profile = {
        "slug": slug,
        "name": "Estación de prueba → Entrada",
        "origin": "Estación de prueba",
        "destination": "Entrada",
        "direction": "outbound",
        "family": "A",
        "points": [
            {"name": "Torniquetes", "lat": 0.0, "lon": 0.0, "instruction": "Sal por la rampa"},
            {
                "name": "Cebra",
                "lat": 0.0005,
                "lon": 0.0,
                "risk": "high",
                "crossing": "zebra",
            },
            {"name": "Entrada", "lat": 0.001, "lon": 0.0},
        ],
    }
    profile.update(fields)
    return profile


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_el_perfil_valida_su_formato():
    profile = RouteProfile.model_validate(_profile())
    assert profile.validated_in_field is False  # sin validar hasta recorrerlo (regla 3)
    assert profile.points[0].approach_m == 60 and profile.points[0].arrive_m == 15
    with pytest.raises(ValidationError):  # al menos 2 puntos
        RouteProfile.model_validate(_profile(points=_profile()["points"][:1]))
    with pytest.raises(ValidationError):  # la llegada va dentro de la aproximación
        bad = _profile()
        bad["points"][0]["arrive_m"] = 80
        RouteProfile.model_validate(bad)
    with pytest.raises(ValidationError):
        RouteProfile.model_validate(_profile(slug="Con Espacios"))
    with pytest.raises(ValidationError):
        RouteProfile.model_validate(_profile(direction="inverted"))


def test_el_panel_carga_reemplaza_y_borra_perfiles(client):
    assert client.put("/api/v1/admin/routes/x", json=_profile()).status_code == 401
    headers = _admin(client)
    r = client.put("/api/v1/admin/routes/estacion-prueba-ida", json=_profile(), headers=headers)
    assert r.status_code == 200
    vuelta = _profile("estacion-prueba-vuelta", direction="return")
    assert (
        client.put(
            "/api/v1/admin/routes/estacion-prueba-vuelta", json=vuelta, headers=headers
        ).status_code
        == 200
    )
    # Reemplazar no duplica.
    client.put(
        "/api/v1/admin/routes/estacion-prueba-ida",
        json=_profile(validated_in_field=True),
        headers=headers,
    )
    profiles = client.get("/api/v1/admin/routes", headers=headers).json()
    assert [p["slug"] for p in profiles] == ["estacion-prueba-ida", "estacion-prueba-vuelta"]
    assert profiles[0]["validated_in_field"] is True
    # El slug de la URL y el del cuerpo deben coincidir.
    assert (
        client.put("/api/v1/admin/routes/otro", json=_profile(), headers=headers).status_code == 400
    )
    assert (
        client.delete("/api/v1/admin/routes/estacion-prueba-vuelta", headers=headers).status_code
        == 204
    )
    assert client.delete("/api/v1/admin/routes/no-existe", headers=headers).status_code == 404


def test_la_app_descarga_los_perfiles_solo_aprobada(client):
    headers = _admin(client)
    client.put("/api/v1/admin/routes/estacion-prueba-ida", json=_profile(), headers=headers)
    assert client.get("/api/v1/devices/me/routes").status_code == 401
    token = _register(client)
    device = {"X-Device-Token": token}
    assert client.get("/api/v1/devices/me/routes", headers=device).status_code == 403
    _set_device(token, status="approved")
    r = client.get("/api/v1/devices/me/routes", headers=device)
    assert r.status_code == 200
    [profile] = r.json()
    assert profile["slug"] == "estacion-prueba-ida"
    assert profile["points"][1]["crossing"] == "zebra"


def test_el_asistente_tiene_las_funciones_de_ruta():
    names = {f["name"] for f in _FUNCTION_DECLARATIONS}
    assert {"start_route", "stop_route", "get_route_progress"} <= names


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("screen_locked", [False, True])
def test_ruta_curada_en_el_prompt(language, screen_locked):
    prompt = c.get_live_system_prompt(language, screen_locked=screen_locked)
    rule = c._ROUTE[language]
    assert rule in prompt
    for word in ("[RUTA]", "start_route", "stop_route", "'none'", "'not validated'"):
        assert word in rule
    assert "'crossing'" in rule and "'finished'" in rule
    # Los cruces siguen la regla CRUCES y, fuera de '[RUTA]', sigue SIN RUTAS.
    assert c._CROSSING[language].split(":")[0].strip() in rule
    assert c._NO_ROUTES[language].split(":")[0].strip() in rule
    assert prompt.index(c._UNICENTRO[language]) < prompt.index(rule)


@pytest.mark.parametrize("language", c.SUPPORTED_LANGUAGES)
def test_con_la_ruta_activa_no_dice_que_no_puede_guiar(language):
    # LAZA-126 (hallazgos 37 y 38): la ruta sigue activa entre dos '[RUTA]', el
    # asistente no la deja por su cuenta y no lee en voz alta la etiqueta.
    rule = c._ROUTE[language]
    for word in ("'ok'", "'already_active'", "'waiting_gps'", "'still guiding'"):
        assert word in rule
    assert rule.count("stop_route") >= 2
    assert "'point'" in rule and "'next'" in rule
