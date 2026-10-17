from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.router import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_health_responde_ok_con_nombre_y_version():
    response = _client().get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "Lazarus Backend"
    assert body["version"]
