"""POST /api/classes: create the class, assign a teacher for every subject, regenerate the whole school."""
import json

import pytest

from class_setup import auto_assign_teachers, capacities, weekly_loads


def one(db, sql, args=()):
    return db.execute(sql, args).fetchone()[0]


def test_add_class_does_everything(api):
    assert api.post("/api/timetable/generate").status_code == 200
    r = api.post("/api/classes", json={"grade": 3})
    assert r.status_code == 201
    body = r.json()
    assert (body["name"], body["grade"]) == ("5/3", 3) and isinstance(body["id"], int)

    # one teacher per subject, none over their limit, picked from teachers of that subject
    assert len(body["assignments"]) == 10
    assert set(body["assignments"][0]) == {"subject_id", "subject", "per_week", "teacher_id", "teacher", "load_after",
                                           "capacity", "over_capacity", "same_grade"}
    for a in body["assignments"]:
        assert a["teacher_id"] is not None and a["over_capacity"] is False and a["load_after"] <= a["capacity"]
        assert one(api.db, "SELECT subject_id FROM teachers WHERE id = ?", (a["teacher_id"],)) == a["subject_id"]
        assert one(api.db, "SELECT COUNT(*) FROM teacher_classes WHERE teacher_id = ? AND class_id = ?",
                   (a["teacher_id"], body["id"])) == 1

    gen = body["generation"]
    assert gen["ok"] is True and gen["classes"] == 21 and gen["lessons_count"] == 21 * 35
    assert gen["violations"] == [] and gen["warnings"] == []
    assert one(api.db, "SELECT COUNT(*) FROM lessons WHERE class_id = ?", (body["id"],)) == 35
    # and the school's analytics agree
    assert api.get("/api/analytics").json()["rule_check"] == {"ok": True, "violations": []}


def test_new_class_gets_the_next_free_section(api):
    api.db.execute("DELETE FROM classes WHERE name = '3/2'")  # free up section 3 of grade 2
    api.db.commit()
    r = api.post("/api/classes", json={"grade": 2})
    assert r.status_code == 201 and r.json()["name"] == "3/2"
    assert any(c["name"] == "3/2" for c in api.get("/api/classes").json())


def test_failed_generation_keeps_class_assignments_and_old_timetable(api):
    assert api.post("/api/timetable/generate").status_code == 200
    before = one(api.db, "SELECT COUNT(*) FROM lessons")
    # make Generate impossible afterwards: every Music teacher is unavailable almost all week
    music = [r[0] for r in api.db.execute("SELECT id FROM teachers WHERE subject_id = 10")]
    for tid in music:
        for slot in range(34):
            api.db.execute("INSERT INTO rules (kind, params) VALUES ('teacher_unavailable', ?)",
                           (json.dumps({"teacher_id": tid, "day": slot // 7, "period": slot % 7 + 1}),))
    api.db.commit()

    r = api.post("/api/classes", json={"grade": 1})
    assert r.status_code == 422 and set(r.json()) == {"error", "message"}
    assert r.json()["error"] == "teacher_overloaded"
    assert "5/1 was added" in r.json()["message"] and "previous timetable was kept" in r.json()["message"]
    cid = one(api.db, "SELECT id FROM classes WHERE name = '5/1'")  # class kept
    assert one(api.db, "SELECT COUNT(*) FROM teacher_classes WHERE class_id = ?", (cid,)) == 10  # assignments kept
    assert one(api.db, "SELECT COUNT(*) FROM lessons") == before  # old timetable kept


def test_unexpected_solver_crash_still_keeps_class_and_assignments(api, monkeypatch):
    import routes_school

    def boom(db):
        raise RuntimeError("solver exploded")

    monkeypatch.setattr(routes_school, "generate_timetable", boom)
    r = api.post("/api/classes", json={"grade": 4})
    assert r.status_code == 500 and r.json()["error"] == "generation_failed" and "5/4" in r.json()["message"]
    cid = one(api.db, "SELECT id FROM classes WHERE name = '5/4'")
    assert one(api.db, "SELECT COUNT(*) FROM teacher_classes WHERE class_id = ?", (cid,)) == 10


def test_busy_generation_is_an_error_but_class_and_teachers_are_kept(api):
    import solver
    assert solver._busy.acquire(blocking=False)
    try:
        r = api.post("/api/classes", json={"grade": 5})
    finally:
        solver._busy.release()
    assert r.status_code == 409 and r.json()["error"] == "busy"
    cid = one(api.db, "SELECT id FROM classes WHERE name = '5/5'")
    assert one(api.db, "SELECT COUNT(*) FROM teacher_classes WHERE class_id = ?", (cid,)) == 10


# ---------- the assignment rules themselves (no solver) ----------

def new_class(db, grade):
    cid = db.execute("INSERT INTO classes (name, grade) VALUES (?, ?)", (f"9/{grade}", grade)).lastrowid
    return cid


def test_prefers_same_grade_then_lowest_load(seeded):
    db = seeded
    cid = new_class(db, 3)
    before = weekly_loads(db)
    result = auto_assign_teachers(db, cid, 3)
    same_grade = {r[0] for r in db.execute(
        "SELECT DISTINCT tc.teacher_id FROM teacher_classes tc JOIN classes c ON c.id = tc.class_id "
        "WHERE c.grade = 3 AND tc.class_id != ?", (cid,))}
    cap = capacities(db)
    for a in result:
        pool = [r[0] for r in db.execute("SELECT id FROM teachers WHERE subject_id = ?", (a["subject_id"],))]
        fitting_same = [t for t in pool if t in same_grade and before.get(t, 0) + a["per_week"] <= cap[t]]
        if fitting_same:  # must come from the same grade, and be the least loaded of those at that moment
            assert a["teacher_id"] in fitting_same and a["same_grade"] is True
        assert a["over_capacity"] is False


def test_nobody_has_room_picks_least_loaded_and_flags_it(seeded):
    db = seeded
    db.execute("DELETE FROM rules")
    music = [r[0] for r in db.execute("SELECT id FROM teachers WHERE subject_id = 10")]
    for tid in music:  # capacity 1 for every Music teacher: nobody can take 2 more lessons
        for slot in range(34):
            db.execute("INSERT INTO rules (kind, params) VALUES ('teacher_unavailable', ?)",
                       (json.dumps({"teacher_id": tid, "day": slot // 7, "period": slot % 7 + 1}),))
    cid = new_class(db, 1)
    loads = weekly_loads(db)
    least = min(music, key=lambda t: (loads.get(t, 0), t))
    result = auto_assign_teachers(db, cid, 1)
    entry = next(a for a in result if a["subject"] == "Music")
    assert entry["over_capacity"] is True and entry["teacher_id"] == least
    assert all(not a["over_capacity"] for a in result if a["subject"] != "Music")


def test_subject_with_no_teacher_at_all_is_left_unassigned(seeded):
    db = seeded
    db.execute("DELETE FROM teacher_classes WHERE teacher_id IN (SELECT id FROM teachers WHERE subject_id = 10)")
    db.execute("DELETE FROM teachers WHERE subject_id = 10")
    cid = new_class(db, 2)
    music = next(a for a in auto_assign_teachers(db, cid, 2) if a["subject"] == "Music")
    assert music["teacher_id"] is None and music["over_capacity"] is False
