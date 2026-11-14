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


# ---- reset and "seed only when empty" ----

def counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("subjects", "classes", "teachers", "teacher_classes", "subject_hours", "rules", "lessons")}


ORIGINAL = {"subjects": 10, "classes": 20, "teachers": 79, "teacher_classes": 200,
            "subject_hours": 50, "rules": 80, "lessons": 0}


def damage(conn):
    """Make changes the way users would: add a rule, a lesson, and delete a teacher."""
    conn.execute("INSERT INTO rules (kind, params, source_text) VALUES ('x', '{}', 'mine')")
    cls = conn.execute("SELECT class_id, teacher_id FROM teacher_classes LIMIT 1").fetchone()
    conn.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) "
                 "SELECT ?, t.id, t.subject_id, 0, 1 FROM teachers t WHERE t.id = ?", (cls["class_id"], cls["teacher_id"]))
    conn.execute("DELETE FROM teachers WHERE id = (SELECT MAX(id) FROM teachers)")
    conn.commit()


def test_reset_restores_the_original_school(client):
    from database.db import get_connection

    conn = get_connection()
    try:
        damage(conn)
        assert counts(conn) != ORIGINAL
        r = client.post("/api/reset")
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert counts(conn) == ORIGINAL
        # ids restart from 1, so the data is identical to a first start
        assert conn.execute("SELECT MIN(id), MAX(id) FROM teachers").fetchone()[:] == (1, 79)
    finally:
        conn.close()


def test_restart_keeps_changes_and_does_not_reseed(tmp_path, monkeypatch):
    from database.db import get_connection

    monkeypatch.setenv("MADAR_DB", str(tmp_path / "persist.db"))
    with TestClient(create_app(frontend_dir=tmp_path / "none")):
        pass  # first start: seeds
    conn = get_connection()
    damage(conn)
    changed = counts(conn)
    conn.close()
    with TestClient(create_app(frontend_dir=tmp_path / "none")):
        pass  # second start: must not touch the data
    conn = get_connection()
    try:
        assert counts(conn) == changed
    finally:
        conn.close()
