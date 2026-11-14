import pytest
from fastapi.testclient import TestClient

from main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App on a temporary empty database. Entering `with` runs startup, like a real server start."""
    monkeypatch.setenv("MADAR_DB", str(tmp_path / "api.db"))
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<h1>Madar</h1>", encoding="utf-8")
    with TestClient(create_app(frontend_dir=frontend)) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_startup_seeds_an_empty_database(client):
    from database.db import get_connection

    conn = get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0] == 79
    finally:
        conn.close()


def test_frontend_is_served_at_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<h1>Madar</h1>" in r.text


def test_api_routes_win_over_static_files(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_unknown_api_path_uses_the_error_shape(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"
    assert isinstance(r.json()["message"], str)


def test_wrong_method_uses_the_error_shape(client):
    r = client.post("/api/health")
    assert r.status_code == 405
    assert r.json()["error"] == "method_not_allowed"


def test_app_starts_without_a_frontend_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("MADAR_DB", str(tmp_path / "x.db"))
    with TestClient(create_app(frontend_dir=tmp_path / "missing")) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/").json()["error"] == "not_found"
