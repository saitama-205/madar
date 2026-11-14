import time

from fastapi.testclient import TestClient

from main import create_app


def test_startup_generates_in_background(tmp_path, monkeypatch):
    monkeypatch.setenv("MADAR_DB", str(tmp_path / "bg.db"))
    monkeypatch.setenv("MADAR_AUTO_GENERATE", "1")
    with TestClient(create_app(frontend_dir=tmp_path / "none")) as client:
        assert client.get("/api/health").json() == {"ok": True}  # answers without waiting for the solver
        deadline = time.time() + 120
        while time.time() < deadline:
            if client.get("/api/timetable?class_id=1").json()["lessons"]:
                break
            time.sleep(1)
        assert len(client.get("/api/timetable?class_id=1").json()["lessons"]) == 35


def test_timetable_empty_when_not_generated(api):
    assert api.get("/api/timetable?class_id=1").json() == {"lessons": []}
