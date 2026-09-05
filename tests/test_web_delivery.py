from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web import mount_frontend


def test_mount_frontend_serves_index_without_shadowing_api(tmp_path):
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text(
        "<!doctype html><title>DELTA</title>",
        encoding="utf-8",
    )

    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    assert mount_frontend(app, frontend_dist) is True

    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>DELTA</title>" in response.text


def test_mount_frontend_is_optional_when_build_is_missing(tmp_path):
    app = FastAPI()

    assert mount_frontend(app, tmp_path / "missing") is False
    assert all(route.name != "frontend" for route in app.routes)
