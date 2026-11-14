"""Absences: short (suggestions for one or several days) and long (reassign classes after confirm)."""
import pytest

import regen
from tests.test_absences import lesson, teachers_of


@pytest.fixture()
def school(api):
    api.db.execute("DELETE FROM lessons")
    api.db.execute("DELETE FROM rules WHERE kind = 'teacher_unavailable'")
    api.db.commit()
    return api


def math_teacher_with_classes(api):
    return next(t for t in api.get("/api/teachers").json() if t["subject_id"] == 4 and t["class_ids"])


# ---------- short ----------

def test_short_mode_is_the_default_and_accepts_several_days(school):
    api = school
    a = math_teacher_with_classes(api)
    c1, c2 = a["class_ids"][:2] if len(a["class_ids"]) > 1 else (a["class_ids"][0], a["class_ids"][0])
    lesson(api, c1, a["id"], 4, 1, 2)
    lesson(api, c2, a["id"], 4, 3, 4)
    one = api.post("/api/absences", json={"teacher_id": a["id"], "day": 1}).json()
    assert [(i["day"], i["period"]) for i in one] == [(1, 2)]
    both = api.post("/api/absences", json={"teacher_id": a["id"], "mode": "short", "days": [3, 1, 1]}).json()
    assert [(i["day"], i["period"]) for i in both] == [(1, 2), (3, 4)]      # sorted, no duplicate days
    assert all(i["substitutes"] for i in both)                              # ranked teachers are always returned


def test_short_mode_needs_a_day(school):
    r = school.post("/api/absences", json={"teacher_id": 1})
    assert r.status_code == 422
    assert school.post("/api/absences", json={"teacher_id": 1, "days": [7]}).status_code == 422


# ---------- long ----------

def test_long_mode_lists_every_class_with_ranked_same_subject_teachers(school):
    api = school
    a = math_teacher_with_classes(api)
    r = api.post("/api/absences", json={"teacher_id": a["id"], "mode": "long"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "long" and body["teacher_id"] == a["id"]
    assert {x["class_id"] for x in body["assignments"]} == set(a["class_ids"])
    for item in body["assignments"]:
        assert set(item) >= {"class_id", "class", "subject_id", "subject", "subject_ar", "per_week", "lessons", "substitutes"}
        assert item["subject"] == "Math" and item["per_week"] in (5, 6) and item["substitutes"]
        subs = item["substitutes"]
        assert all(s["teacher_id"] != a["id"] for s in subs)
        assert all(x["subject_id"] == 4 for x in api.get("/api/teachers").json() if x["id"] in {s["teacher_id"] for s in subs})
        keys = [(s["over_capacity"], s["clashes"], s["load"], s["teacher_id"]) for s in subs]
        assert keys == sorted(keys)                                           # best first
        assert set(subs[0]) == {"teacher_id", "name", "reason", "load", "load_after", "capacity", "over_capacity", "clashes"}


def test_long_mode_with_no_other_teacher_says_so(school):
    api = school
    a = math_teacher_with_classes(api)
    api.db.execute("DELETE FROM teachers WHERE subject_id = 4 AND id != ?", (a["id"],))
    api.db.commit()
    body = api.post("/api/absences", json={"teacher_id": a["id"], "mode": "long"}).json()
    assert all(x["substitutes"] == [] for x in body["assignments"]) and "no other Math teacher" in body["warnings"][0]


def test_long_mode_unknown_teacher_is_404(school):
    assert school.post("/api/absences", json={"teacher_id": 99999, "mode": "long"}).status_code == 404


def pick_substitute(api, a, class_id):
    body = api.post("/api/absences", json={"teacher_id": a["id"], "mode": "long"}).json()
    item = next(x for x in body["assignments"] if x["class_id"] == class_id)
    return item["substitutes"][0]["teacher_id"]


def test_apply_reassigns_and_regenerates(school, monkeypatch):
    api = school
    monkeypatch.setenv("MADAR_AUTO_REGENERATE", "1")
    calls = []
    monkeypatch.setattr(regen.solver, "generate_timetable", lambda db: calls.append(1) or {"lessons_count": 1, "seconds": 0, "warnings": []})
    a = math_teacher_with_classes(api)
    cid = a["class_ids"][0]
    sub = pick_substitute(api, a, cid)
    r = api.post("/api/absences/apply", json={"teacher_id": a["id"], "assignments": [{"class_id": cid, "substitute_id": sub}]})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ok"] is True and body["generated"] is True and calls == [1] and "violations" in body and "warnings" in body
    assert body["reassigned"] == [{"class_id": cid, "class": body["reassigned"][0]["class"], "subject_id": 4, "subject": "Math",
                                   "from_teacher_id": a["id"], "to_teacher_id": sub, "to_teacher": body["reassigned"][0]["to_teacher"]}]
    now = {t["id"]: t["class_ids"] for t in api.get("/api/teachers").json()}
    assert cid not in now[a["id"]] and cid in now[sub]
    # the class still has exactly one Math teacher
    assert sum(cid in ids for tid, ids in now.items() if tid in teachers_of(api, 4)) == 1


def test_apply_keeps_the_assignment_when_the_solve_fails(school, monkeypatch):
    api = school
    from errors import ApiError
    monkeypatch.setenv("MADAR_AUTO_REGENERATE", "1")
    def boom(db):
        raise ApiError(409, "infeasible", "No timetable can satisfy all the rules.")
    monkeypatch.setattr(regen.solver, "generate_timetable", boom)
    a = math_teacher_with_classes(api)
    cid = a["class_ids"][0]
    lesson(api, cid, a["id"], 4, 0, 1)
    sub = pick_substitute(api, a, cid)
    r = api.post("/api/absences/apply", json={"teacher_id": a["id"], "assignments": [{"class_id": cid, "substitute_id": sub}]})
    assert r.status_code == 200 and r.json()["generated"] is False and r.json()["error"] == "infeasible"
    assert api.db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 1          # old timetable kept


def test_apply_rejects_bad_choices_and_changes_nothing(school):
    api = school
    a = math_teacher_with_classes(api)
    cid = a["class_ids"][0]
    english = teachers_of(api, 3)[0]
    other_math = next(t for t in teachers_of(api, 4) if t != a["id"])
    before = api.db.execute("SELECT COUNT(*) FROM teacher_classes").fetchone()[0], a["class_ids"]
    post = lambda **kw: api.post("/api/absences/apply", json={"teacher_id": a["id"], **kw})
    r = post(assignments=[{"class_id": cid, "substitute_id": english}])
    assert r.status_code == 422 and r.json()["error"] == "invalid_substitute"          # different subject
    assert post(assignments=[{"class_id": cid, "substitute_id": a["id"]}]).status_code == 422   # themselves
    assert post(assignments=[{"class_id": cid, "substitute_id": 99999}]).status_code == 404
    assert post(assignments=[{"class_id": 99999, "substitute_id": other_math}]).status_code == 404
    assert post(assignments=[{"class_id": cid, "substitute_id": other_math}, {"class_id": cid, "substitute_id": other_math}]).status_code == 422
    assert post(assignments=[]).status_code == 422
    assert api.post("/api/absences/apply", json={"teacher_id": 99999, "assignments": [{"class_id": cid, "substitute_id": other_math}]}).status_code == 404
    assert (api.db.execute("SELECT COUNT(*) FROM teacher_classes").fetchone()[0], a["class_ids"]) == before


def test_apply_refuses_a_substitute_without_room(school):
    api = school
    a = math_teacher_with_classes(api)
    cid = a["class_ids"][0]
    other = next(t for t in teachers_of(api, 4) if t != a["id"])
    for slot in range(35):                      # make `other` unavailable almost all week -> no room for more lessons
        api.db.execute("INSERT INTO rules (kind, params) VALUES ('teacher_unavailable', ?)",
                       (f'{{"teacher_id": {other}, "day": {slot // 7}, "period": {slot % 7 + 1}}}',))
    api.db.commit()
    r = api.post("/api/absences/apply", json={"teacher_id": a["id"], "assignments": [{"class_id": cid, "substitute_id": other}]})
    assert r.status_code == 409 and r.json()["error"] == "substitute_over_capacity"
    assert cid in next(t for t in api.get("/api/teachers").json() if t["id"] == a["id"])["class_ids"]
