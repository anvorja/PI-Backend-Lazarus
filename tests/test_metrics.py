"""Métricas de capacidad: muestreo del proceso, resumen por plataforma y endpoint del panel."""

from datetime import timedelta

import psutil
import pytest
from fastapi.testclient import TestClient

from app.db.models import AdminUser, MetricSample
from app.db.session import SessionLocal
from app.main import app
from app.services import access, metrics
from app.services.admin_auth import hash_password


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_counters():
    metrics._active_sessions = 0
    metrics._bytes_up = 0
    metrics._bytes_down = 0
    yield


def _admin(client) -> dict:
    with SessionLocal() as db:
        db.add(AdminUser(username="coordinador", password_hash=hash_password("clave-larga-1")))
        db.commit()
    r = client.post(
        "/api/v1/admin/login", json={"username": "coordinador", "password": "clave-larga-1"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _row(minutes_ago: float = 0, platform="render", cpu=10.0, rss=100.0, sessions=0, up=0, down=0):
    return MetricSample(
        ts=access.utcnow() - timedelta(minutes=minutes_ago),
        platform=platform,
        cpu_pct=cpu,
        rss_mb=rss,
        active_sessions=sessions,
        bytes_up=up,
        bytes_down=down,
        loop_lag_ms=1.0,
        interval_s=30.0,
    )


def test_los_contadores_de_sesiones_y_trafico_se_acumulan():
    metrics.session_opened()
    metrics.session_opened()
    metrics.session_closed()
    metrics.add_bytes(up=1000, down=500)
    assert metrics.active_sessions() == 1
    assert (metrics._bytes_up, metrics._bytes_down) == (1000, 500)
    metrics.session_closed()
    metrics.session_closed()  # nunca baja de cero
    assert metrics.active_sessions() == 0


def test_la_muestra_trae_el_trafico_del_intervalo():
    process = psutil.Process()
    metrics.add_bytes(up=300, down=200)
    metrics.session_opened()
    sample, up, down = metrics.take_sample(process, 100, 50, lag_s=0.012, interval_s=30)
    assert (sample.bytes_up, sample.bytes_down) == (200, 150)
    assert (up, down) == (300, 200)
    assert sample.active_sessions == 1
    assert sample.rss_mb > 0
    assert sample.loop_lag_ms == 12.0


def test_resumen_estima_costo_por_sesion():
    rows = [
        _row(rss=100, sessions=0),
        _row(rss=100, sessions=0),
        _row(rss=130, sessions=2, cpu=8, up=60_000, down=90_000),
        _row(rss=130, sessions=2, cpu=12, up=60_000, down=90_000),
    ]
    s = metrics.summarize(rows)
    assert s["sessions_max"] == 2
    assert s["cpu_max"] == 12
    assert s["cpu_per_session"] == 5.0  # 10 % medio entre 2 sesiones
    assert s["mb_per_session"] == 15.0  # 30 MB sobre la base entre 2 sesiones
    assert s["kbps_per_session"] == 20.0  # 150 KB en 30 s = 40 kbps, entre 2 sesiones


def test_resumen_sin_sesiones_no_inventa_costos():
    s = metrics.summarize([_row(), _row()])
    assert "cpu_per_session" not in s
    assert metrics.summarize([]) == {"samples": 0}


def test_la_serie_se_reduce_a_un_maximo_de_puntos():
    rows = [_row() for _ in range(metrics.MAX_POINTS * 3 + 7)]
    assert len(metrics.downsample(rows)) <= metrics.MAX_POINTS


def test_el_panel_exige_sesion_para_ver_las_metricas(client):
    assert client.get("/api/v1/admin/metrics").status_code == 401


def test_el_panel_separa_las_plataformas_y_filtra_por_horas(client):
    headers = _admin(client)
    with SessionLocal() as db:
        db.add_all(
            [
                _row(minutes_ago=5, platform="render"),
                _row(minutes_ago=5, platform="aws"),
                _row(minutes_ago=60 * 10, platform="render"),  # fuera de las 6 h
            ]
        )
        db.commit()
    body = client.get("/api/v1/admin/metrics", headers=headers).json()
    assert set(body["summary"]) == {"render", "aws"}
    assert body["summary"]["render"]["samples"] == 1
    assert len(body["series"]) == 2

    only_aws = client.get("/api/v1/admin/metrics?platform=aws", headers=headers).json()
    assert [p["platform"] for p in only_aws["series"]] == ["aws"]

    wide = client.get("/api/v1/admin/metrics?hours=24", headers=headers).json()
    assert wide["summary"]["render"]["samples"] == 2
    assert client.get("/api/v1/admin/metrics?hours=0", headers=headers).status_code == 422
