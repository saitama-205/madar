"""POST /api/timetable/generate: the solver, its rules, and its error messages."""
import json
from collections import Counter

import solver


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def add_rule(db, kind, **params):
    db.execute("INSERT INTO rules (kind, params, source_text) VALUES (?, ?, 'test')", (kind, json.dumps(params)))
    db.commit()


def subject_id(db, name):
    return one(db, "SELECT id FROM subjects WHERE name = ?", name)


def check_timetable(db):
    """Independent check of every contract hard rule against what is saved in `lessons`."""
    lessons = [tuple(r) for r in db.execute("SELECT class_id, teacher_id, subject_id, day, period FROM lessons")]
    grade = {r["id"]: r["grade"] for r in db.execute("SELECT id, grade FROM classes")}
    subject = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM subjects")}
    hours = {(r["grade"], r["subject_id"]): r["per_week"] for r in db.execute("SELECT * FROM subject_hours")}
    assigned = {(r["class_id"], r["teacher_id"]) for r in db.execute("SELECT class_id, teacher_id FROM teacher_classes")}
    teacher_subject = {r["id"]: r["subject_id"] for r in db.execute("SELECT id, subject_id FROM teachers")}

    # 1. every class has exactly one lesson in every one of its 35 slots
    per_slot = Counter((c, d, p) for c, _, _, d, p in lessons)
    assert all(n == 1 for n in per_slot.values()), "a class has two lessons in one slot"
    for c in grade:
        assert {(d, p) for cc, d, p in per_slot if cc == c} == {(d, p) for d in range(5) for p in range(1, 8)}, c
    # 2. a teacher is never in two places at once
    assert all(n == 1 for n in Counter((t, d, p) for _, t, _, d, p in lessons).values()), "teacher double-booked"
    # 3. exactly per_week lessons of each subject per class
    got = Counter((c, s) for c, _, s, _, _ in lessons)
    for c, g in grade.items():
        for (hg, s), h in hours.items():
            if hg == g:
                assert got[(c, s)] == h, (c, subject[s], got[(c, s)], h)
    # 4. the lesson's teacher is the one assigned to that class, and teaches that subject
    for c, t, s, _, _ in lessons:
        assert (c, t) in assigned and teacher_subject[t] == s
    # 5. all saved rules are kept
    for r in db.execute("SELECT kind, params FROM rules"):
        p = json.loads(r["params"])
        if r["kind"] == "subject_not_in_period":
            assert not any(s == p["subject_id"] and pe == p["period"] for _, _, s, _, pe in lessons)
        elif r["kind"] == "teacher_unavailable":
            assert not any(t == p["teacher_id"] and d == p["day"] and pe == p["period"] for _, t, _, d, pe in lessons)
        elif r["kind"] == "pin_lesson":
            assert (p["class_id"], p["subject_id"], p["day"], p["period"]) in {(c, s, d, pe) for c, _, s, d, pe in lessons
                                                                               if c == p["class_id"] and s == p["subject_id"]}
    # 6. daily cap: 2 for Arabic/Math/Art/Music, 1 for the rest
    for (c, s, d), n in Counter((c, s, d) for c, _, s, d, _ in lessons).items():
        assert n <= (2 if subject[s] in ("Arabic", "Math", "Art", "Music") else 1), (c, subject[s], d, n)
    # 7. parallel cap
    caps = {"Science": 2, "Computer": 2, "Art": 4, "PE": 4, "Music": 2}
    for (s, d, p), n in Counter((s, d, p) for _, _, s, d, p in lessons).items():
        assert n <= caps.get(subject[s], 99), (subject[s], d, p, n)
    return len(lessons)


# ---------- success ----------

def test_generate_builds_a_valid_timetable(api):
    r = api.post("/api/timetable/generate")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["lessons_count"] == 700 and isinstance(body["seconds"], (int, float))
    assert check_timetable(api.db) == 700  # includes the 80 seeded "lighter teacher" rules


def test_timetable_endpoint_shows_the_generated_lessons(api):
    api.post("/api/timetable/generate")
    lessons = api.get("/api/timetable", params={"class_id": 1}).json()["lessons"]
    assert len(lessons) == 35
    assert len({(x["day"], x["period"]) for x in lessons}) == 35
    teacher = lessons[0]["teacher_id"]
    mine = api.get("/api/timetable", params={"teacher_id": teacher}).json()["lessons"]
    assert mine and all(x["teacher_id"] == teacher for x in mine)


def test_generating_again_replaces_the_lessons(api):
    api.post("/api/timetable/generate")
    api.post("/api/timetable/generate")
    assert one(api.db, "SELECT COUNT(*) FROM lessons") == 700
    check_timetable(api.db)


def test_saved_rules_are_kept(api):
    db = api.db
    pe, math = subject_id(db, "PE"), subject_id(db, "Math")
    tid = one(db, "SELECT id FROM teachers WHERE subject_id = ? ORDER BY id LIMIT 1", subject_id(db, "Arabic"))
    add_rule(db, "subject_not_in_period", subject_id=pe, period=7)
    add_rule(db, "subject_not_in_period", subject_id=pe, period=1)
    for p in range(1, 8):
        add_rule(db, "teacher_unavailable", teacher_id=tid, day=0, period=p)  # that teacher is off on Sunday
    add_rule(db, "pin_lesson", class_id=1, subject_id=math, day=1, period=3)
    assert api.post("/api/timetable/generate").status_code == 200
    check_timetable(db)
    pinned = [x for x in api.get("/api/timetable", params={"class_id": 1}).json()["lessons"]
              if (x["day"], x["period"]) == (1, 3)]
    assert pinned[0]["subject"] == "Math"


# ---------- errors say what is wrong, and never wipe the old timetable ----------

def test_missing_teachers_are_named(api):
    api.post("/api/timetable/generate")
    api.post("/api/classes", json={"grade": 1})  # new class 5/1 has no teachers
    r = api.post("/api/timetable/generate")
    assert r.status_code == 422 and r.json()["error"] == "missing_teachers"
    assert "5/1" in r.json()["message"] and "Arabic" in r.json()["message"]
    assert one(api.db, "SELECT COUNT(*) FROM lessons") == 700  # old timetable untouched


def test_hours_that_do_not_add_up_to_35(api):
    api.db.execute("UPDATE subject_hours SET per_week = per_week + 1 WHERE grade = 2 AND subject_id = 1")
    api.db.commit()
    r = api.post("/api/timetable/generate")
    assert r.status_code == 422 and r.json()["error"] == "bad_hours"
    assert "Grade 2" in r.json()["message"] and "36" in r.json()["message"]


def test_two_teachers_for_one_class_and_subject(api):
    db = api.db
    arabic = subject_id(db, "Arabic")
    other = one(db, """SELECT t.id FROM teachers t WHERE t.subject_id = ?
                       AND t.id NOT IN (SELECT teacher_id FROM teacher_classes WHERE class_id = 1) LIMIT 1""", arabic)
    db.execute("INSERT INTO teacher_classes (teacher_id, class_id) VALUES (?, 1)", (other,))
    db.commit()
    r = api.post("/api/timetable/generate")
    assert r.status_code == 422 and r.json()["error"] == "multiple_teachers"


def test_teacher_with_too_few_free_slots(api):
    db = api.db
    tid = one(db, "SELECT teacher_id FROM teacher_classes GROUP BY teacher_id ORDER BY COUNT(*) DESC LIMIT 1")
    for d in range(5):
        for p in range(1, 8):
            add_rule(db, "teacher_unavailable", teacher_id=tid, day=d, period=p)
    r = api.post("/api/timetable/generate")
    assert r.status_code == 422 and r.json()["error"] == "teacher_overloaded"
    assert one(db, "SELECT name FROM teachers WHERE id = ?", tid) in r.json()["message"]


def test_impossible_rules_give_infeasible_and_keep_the_old_timetable(api):
    db = api.db
    api.post("/api/timetable/generate")
    # one teacher with two classes, both pinned to the same slot: she cannot be in two places
    row = db.execute("""SELECT t.id, t.subject_id, MIN(tc.class_id) AS a, MAX(tc.class_id) AS b
                        FROM teachers t JOIN teacher_classes tc ON tc.teacher_id = t.id
                        GROUP BY t.id HAVING COUNT(*) >= 2 LIMIT 1""").fetchone()
    for cls in (row["a"], row["b"]):
        add_rule(db, "pin_lesson", class_id=cls, subject_id=row["subject_id"], day=2, period=4)
    r = api.post("/api/timetable/generate")
    assert r.status_code == 409 and r.json()["error"] == "infeasible"
    assert one(db, "SELECT COUNT(*) FROM lessons") == 700


def test_rules_that_point_at_nothing_are_reported(api):
    db = api.db
    add_rule(db, "teacher_unavailable", teacher_id=99999, day=0, period=1)
    r = api.post("/api/timetable/generate")
    assert r.status_code == 422 and r.json()["error"] == "invalid_rule" and "Rule" in r.json()["message"]
    db.execute("DELETE FROM rules WHERE kind = 'teacher_unavailable' AND params LIKE '%99999%'")
    add_rule(db, "pin_lesson", class_id=1)  # settings missing
    assert api.post("/api/timetable/generate").json()["error"] == "invalid_rule"


def test_only_one_generation_at_a_time(api):
    assert solver._busy.acquire(blocking=False)
    try:
        r = api.post("/api/timetable/generate")
        assert r.status_code == 409 and r.json()["error"] == "busy"
    finally:
        solver._busy.release()
