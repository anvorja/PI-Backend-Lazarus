"""Perfil de ruta curado (HU-022): una estación, un sentido, sus puntos en orden.

El perfil se arma a mano con lo verificado en campo (Fase 0, HU-014). Las
coordenadas no van en el repositorio: el perfil se carga en la base de datos
desde el panel (o `scripts/load_route.py`) y la app lo descarga con su token.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RoutePoint(BaseModel):
    """Un punto del recorrido: referencia, cruce o riesgo, en el orden en que se pasa."""

    name: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    # Qué hacer al llegar, con las palabras del perfil ("sigue la rampa con barandas").
    instruction: str = Field(default="", max_length=200)
    risk: Literal["low", "medium", "high"] = "low"
    # Tipo de cruce de vía, si el punto es uno (HU-020).
    crossing: Literal["traffic_light", "zebra", "uncontrolled"] | None = None
    # Geocercas (HU-018, regla 1): aproximación ~60 m y llegada ~15 m.
    approach_m: float = Field(default=60, gt=0, le=300)
    arrive_m: float = Field(default=15, gt=0, le=100)

    @model_validator(mode="after")
    def _arrive_inside_approach(self) -> "RoutePoint":
        if self.arrive_m >= self.approach_m:
            raise ValueError("arrive_m debe ser menor que approach_m")
        return self


class RouteProfile(BaseModel):
    """Ida y vuelta son perfiles distintos: la vuelta no es la ida invertida
    (HU-022, regla 2)."""

    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)
    name: str = Field(min_length=1, max_length=120)
    origin: str = Field(min_length=1, max_length=80)
    destination: str = Field(min_length=1, max_length=80)
    direction: Literal["outbound", "return"]
    family: Literal["A", "B", "other"] = "other"
    # Sin validar en campo, solo se usa acompañado y la app lo advierte (regla 3).
    validated_in_field: bool = False
    points: list[RoutePoint] = Field(min_length=2, max_length=60)
