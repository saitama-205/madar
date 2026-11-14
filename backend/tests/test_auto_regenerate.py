"""Every endpoint that changes data regenerates the timetable and reports {generated, violations, warnings}.
The solver is faked here (the real one takes seconds); a failed solve must leave the old lessons alone."""
import pytest

import regen
from errors import ApiError


@pytest.fixture()
def solver(api, monkeypatch):
    monkeypatch.setenv("MADAR_AUTO_REGENERATE", "1")
    box = type("Box", (), {"calls": 0, "fail": None})()

    def fake(db):
        box.calls += 1
        if box.fail:
            raise box.fail
        return {"ok": True, "lessons_count": 7, "seconds": 0.1, "warnings": ["skipped something"]}

    monkeypatch.setattr(regen.solver, "generate_timetable", fake)
    return box


def lessons(api):
    return api.db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]


def check(r, box, calls=1):
    body = r.json()
    assert r.status_code in (200, 201), body
    assert body["generated"] is True and body["warnings"] == ["skipped something"] and isinstance(body["violations"], list)
    assert box.calls == calls


def test_add_rule_regenerates(api, solver):
    check(api.post("/api/rules", json={"kind": "subject_not_in_period", "params": {"subject_id": 1, "period": 7}}), solver)


def test_delete_rule_regenerates(api, solver):
    rid = api.get("/api/rules").json()[0]["id"]
    check(api.delete(f"/api/rules/{rid}"), solver)


def test_add_teacher_regenerates(api, solver):
    check(api.post("/api/teachers", json={"name": "Sara Z", "subject_id": 1, "class_ids": []}), solver)


def test_add_class_still_reports_generated(api, monkeypatch):
    monkeypatch.setattr("routes_school.generate_timetable", lambda db: {"ok": True, "lessons_count": 7, "seconds": 0.1, "warnings": []})
    api.db.execute("DELETE FROM lessons"); api.db.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (1, 1, 1, 0, 1)")
    api.db.commit()
    body = api.post("/api/classes", json={"grade": 3}).json()
    assert body["generated"] is True and "violations" in body and "warnings" in body


def test_failed_solve_keeps_the_timetable_and_the_change(api, solver):
    api.db.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (1, 1, 1, 0, 1)")
    api.db.commit()
    solver.fail = ApiError(409, "infeasible", "No timetable can satisfy all the rules.")
    r = api.post("/api/rules", json={"kind": "subject_not_in_period", "params": {"subject_id": 1, "period": 7}})
    body = r.json()
    assert r.status_code == 201 and body["generated"] is False and body["error"] == "infeasible"
    assert "No timetable can satisfy" in body["warnings"][0] and "previous timetable was kept" in body["warnings"][0]
    assert lessons(api) == 1                                                       # old timetable untouched
    assert any(x["id"] == body["id"] for x in api.get("/api/rules").json())      # the rule itself is saved


def test_unexpected_solver_crash_is_reported_not_raised(api, solver):
    solver.fail = RuntimeError("boom")
    r = api.post("/api/rules", json={"kind": "subject_not_in_period", "params": {"subject_id": 1, "period": 7}})
    assert r.status_code == 201 and r.json()["generated"] is False and r.json()["error"] == "generation_failed"


def test_busy_solver_is_reported(api, solver):
    solver.fail = ApiError(409, "busy", "A timetable is already being generated.")
    assert api.delete(f"/api/rules/{api.get('/api/rules').json()[0]['id']}").json()["error"] == "busy"


def test_real_solver_failure_does_not_wipe_lessons(api, monkeypatch):
    """No fake: break the data so the real solver refuses, and check the lessons survive."""
    monkeypatch.setenv("MADAR_AUTO_REGENERATE", "1")
    api.db.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (1, 1, 1, 0, 1)")
    api.db.execute("UPDATE subject_hours SET per_week = per_week + 1 WHERE grade = 1 AND subject_id = 1")  # grade 1 now 36
    api.db.commit()
    body = api.delete(f"/api/rules/{api.get('/api/rules').json()[0]['id']}").json()
    assert body["generated"] is False and body["error"] == "bad_hours"
    assert lessons(api) == 1
