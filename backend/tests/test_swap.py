"""Swap two lessons of one class via POST /api/rules/parse (preview) and POST /api/rules {rules: [..]} (confirm)."""
import json

import pytest

from ai import llm
from tests.test_rules_parse import ai, parse  # noqa: F401  (the fake AI fixture)

MATH, ARABIC, ENGLISH = 4, 2, 3


def subject_ids(api):
    return {s["name"]: s["id"] for s in api.get("/api/subjects").json()}


@pytest.fixture()
def timetable(api):
    """Class 1/1 has Math Sunday p1 and Arabic Tuesday p3 (a partial timetable is enough: only NEW violations count)."""
    ids = subject_ids(api)
    cls = api.db.execute("SELECT id FROM classes WHERE name = '1/1'").fetchone()[0]
    teacher = lambda sid: api.db.execute("""SELECT t.id FROM teachers t JOIN teacher_classes tc ON tc.teacher_id = t.id
                                            WHERE t.subject_id = ? AND tc.class_id = ?""", (sid, cls)).fetchone()[0]
    api.db.execute("DELETE FROM lessons")
    api.db.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, 0, 1)",
                   (cls, teacher(ids["Math"]), ids["Math"]))
    api.db.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, 2, 3)",
                   (cls, teacher(ids["Arabic"]), ids["Arabic"]))
    api.db.commit()
    return {"class_id": cls, "ids": ids, "teacher": teacher, "rules_before": len(api.get("/api/rules").json())}


SWAP = {"kind": "swap_lessons", "class": "1/1", "day1": "Sunday", "period1": 1, "day2": "Tuesday", "period2": 3}


def test_swap_preview_has_two_pins_and_saves_nothing(api, ai, timetable):
    ai.answer = SWAP
    r = parse(api, "swap class 1/1 Sunday period 1 with Tuesday period 3")
    assert r.status_code == 200, r.json()
    body, ids, cls = r.json(), timetable["ids"], timetable["class_id"]
    assert body["rules"] == [
        {"kind": "pin_lesson", "params": {"class_id": cls, "subject_id": ids["Math"], "day": 2, "period": 3}},
        {"kind": "pin_lesson", "params": {"class_id": cls, "subject_id": ids["Arabic"], "day": 0, "period": 1}}]
    assert (body["kind"], body["params"]) == (body["rules"][0]["kind"], body["rules"][0]["params"])
    assert body["swap"]["a"] == {"day": 0, "period": 1, "subject_id": ids["Math"]}
    assert "Math" in body["explanation"] and "Arabic" in body["explanation"] and "swap" in body["explanation"]
    assert len(api.get("/api/rules").json()) == timetable["rules_before"]


def test_swap_names_are_case_insensitive_and_arabic_works(api, ai, timetable):
    ai.answer = {**SWAP, "kind": "SWAP_LESSONS", "day1": "sUNDAY", "day2": "TUESDAY"}
    assert parse(api, "x").status_code == 200
    ai.answer = {"kind": "swap_lessons", "class": "١/١", "day1": "الأحد", "period1": "١", "day2": "الثلاثاء", "period2": "٣"}
    r = parse(api, "بدّل حصة الصف 1/1 يوم الأحد الحصة 1 مع الثلاثاء الحصة 3")
    assert r.status_code == 200, r.json()
    assert "الرياضيات" in r.json()["explanation"] and "الثلاثاء" in r.json()["explanation"]


def test_swap_confirm_saves_both_pins_at_once(api, ai, timetable):
    ai.answer = SWAP
    rules = parse(api, "x").json()["rules"]
    r = api.post("/api/rules", json={"rules": rules, "source_text": "swap"})
    assert r.status_code == 201 and len(r.json()["rules"]) == 2
    assert set(r.json()) >= {"generated", "violations", "warnings"}
    assert len(api.get("/api/rules").json()) == timetable["rules_before"] + 2
    again = api.post("/api/rules", json={"rules": rules})          # saving it twice is harmless
    assert again.status_code == 201 and again.json()["rules"] == []


def test_swap_rejected_when_teacher_unavailable(api, ai, timetable):
    math_teacher = timetable["teacher"](timetable["ids"]["Math"])
    api.post("/api/rules", json={"kind": "teacher_unavailable", "params": {"teacher_id": math_teacher, "day": 2, "period": 3}})
    ai.answer = SWAP
    r = parse(api, "x")
    assert r.status_code == 422 and r.json()["error"] == "swap_breaks_rule"
    assert "would break a rule" in r.json()["message"] and "unavailable" in r.json()["message"]


def test_swap_rejected_when_subject_banned_from_period(api, ai, timetable):
    api.post("/api/rules", json={"kind": "subject_not_in_period", "params": {"subject_id": timetable["ids"]["Math"], "period": 3}})
    ai.answer = SWAP
    r = parse(api, "x")
    assert r.status_code == 422 and r.json()["error"] == "swap_breaks_rule" and "never" in r.json()["message"]


def test_swap_rejected_when_it_breaks_an_existing_pin(api, ai, timetable):
    api.post("/api/rules", json={"kind": "pin_lesson", "params": {
        "class_id": timetable["class_id"], "subject_id": timetable["ids"]["Math"], "day": 0, "period": 1}})
    ai.answer = SWAP
    r = parse(api, "x")
    assert r.status_code == 422 and "pinned" in r.json()["message"]


def test_swap_rejected_when_teacher_is_busy_elsewhere(api, ai, timetable):
    other = api.db.execute("SELECT id FROM classes WHERE name = '2/1'").fetchone()[0]
    arabic_teacher = timetable["teacher"](timetable["ids"]["Arabic"])
    # the Arabic teacher would have to be in class 1/1 on Sunday p1 while teaching 2/1 then
    api.db.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, 0, 1)",
                   (other, arabic_teacher, timetable["ids"]["Arabic"]))
    api.db.commit()
    ai.answer = SWAP
    r = parse(api, "x")
    assert r.status_code == 422 and r.json()["error"] == "swap_breaks_rule"
    assert api.db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 3     # nothing was changed


def test_swap_does_not_change_the_saved_timetable(api, ai, timetable):
    ai.answer = SWAP
    before = [tuple(r) for r in api.db.execute("SELECT class_id, teacher_id, subject_id, day, period FROM lessons ORDER BY id")]
    assert parse(api, "x").status_code == 200
    assert before == [tuple(r) for r in api.db.execute("SELECT class_id, teacher_id, subject_id, day, period FROM lessons ORDER BY id")]


def test_swap_errors(api, ai, timetable):
    ai.answer = {**SWAP, "period2": 5}                  # no lesson there
    assert parse(api, "x").status_code == 422
    ai.answer = {**SWAP, "day2": "Sunday", "period2": 1}   # same slot
    assert parse(api, "x").status_code == 422
    ai.answer = {**SWAP, "day2": "Friday"}
    assert parse(api, "x").status_code == 422
    ai.answer = {**SWAP, "class": "9/9"}
    assert parse(api, "x").status_code == 422
    api.db.execute("DELETE FROM lessons"); api.db.commit()
    ai.answer = SWAP
    r = parse(api, "x")
    assert r.status_code == 409 and r.json()["error"] == "no_timetable"
