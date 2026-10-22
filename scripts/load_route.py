"""Carga (o reemplaza) un perfil de ruta curado en el backend (HU-022).

Los perfiles llevan coordenadas: no se versionan en el repositorio. Se guardan en
la base de datos a través de la API del panel, con la sesión del administrador.

    uv run python scripts/load_route.py perfil.json --url https://<backend> --user <admin>

La clave se pide por teclado y no se muestra ni se guarda. El archivo se valida
con el mismo esquema del backend antes de enviarlo.
"""

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.route_profile import RouteProfile  # noqa: E402


def _request(method: str, url: str, body: dict | None = None, token: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read() or b"{}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("profile", type=Path, help="archivo JSON del perfil")
    parser.add_argument("--url", required=True, help="URL del backend, sin /api/v1")
    parser.add_argument("--user", required=True, help="usuario administrador del panel")
    args = parser.parse_args()

    profile = RouteProfile.model_validate_json(args.profile.read_text(encoding="utf-8"))
    base = args.url.rstrip("/") + "/api/v1/admin"
    password = getpass.getpass(f"Clave de {args.user}: ")
    try:
        login = _request("POST", f"{base}/login", {"username": args.user, "password": password})
        _request(
            "PUT",
            f"{base}/routes/{profile.slug}",
            profile.model_dump(mode="json"),
            token=login["access_token"],
        )
    except urllib.error.HTTPError as e:
        print(f"No se cargó: HTTP {e.code}", file=sys.stderr)
        return 1
    print(f"Perfil '{profile.slug}' cargado: {len(profile.points)} puntos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
