import json

import pytest

from ai import llm


@pytest.fixture()
def ai(monkeypatch):
    """Fake AI: set ai.answer to the JSON dict (or text) the model should 'say'. Records the prompts it was sent."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    box = type("Box", (), {"answer": {}, "sent": []})()

    def fake_send(payload, headers):
        box.sent.append(payload["messages"])
        text = box.answer if isinstance(box.answer, str) else json.dumps(box.answer)
        return 200, json.dumps({"choices": [{"message": {"content": text}}]})

    monkeypatch.setattr(llm, "_send", fake_send)
    return box


def parse(api, text):
    return api.post("/api/rules/parse", json={"text": text})


def test_no_key_is_503_not_a_crash(api, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(llm, "ENV_FILE", llm.ENV_FILE.with_name("nope.env"))
    r = parse(api, "PE never in period 7")
    assert r.status_code == 503 and r.json()["error"] == "ai_unavailable"


def test_subject_not_in_period_preview_saves_nothing(api, ai):
    ai.answer = {"kind": "subject_not_in_period", "subject": "PE", "period": 7}
    r = parse(api, "PE never in period 7")
    assert r.status_code == 200
    body = r.json()
    pe = next(s["id"] for s in api.get("/api/subjects").json() if s["name"] == "PE")
    assert body["kind"] == "subject_not_in_period" and body["params"] == {"subject_id": pe, "period": 7}
    assert body["explanation"] == "PE will never be in period 7."
    before = len(api.get("/api/rules").json())
    parse(api, "PE never in period 7")
    assert len(api.get("/api/rules").json()) == before


def test_arabic_values_are_normalized(api, ai):
    ai.answer = {"kind": "subject_not_in_period", "subject": "الرياضيات", "period": "٧"}
    r = parse(api, "الرياضيات ما تكون في الحصة ٧")
    assert r.status_code == 200 and r.json()["params"]["period"] == 7
    assert "الرياضيات" in r.json()["explanation"]


def test_teacher_unavailable(api, ai):
    tid = api.get("/api/teachers").json()[0]["id"]
    ai.answer = {"kind": "teacher_unavailable", "teacher_id": tid, "day": "الأحد", "period": 3}
    r = parse(api, "x")
    assert r.status_code == 200 and r.json()["params"] == {"teacher_id": tid, "day": 0, "period": 3}


def test_pin_lesson(api, ai):
    ai.answer = {"kind": "pin_lesson", "class": "1/1", "subject": "Math", "day": "Monday", "period": 2}
    r = parse(api, "x")
    assert r.status_code == 200 and r.json()["kind"] == "pin_lesson" and r.json()["params"]["day"] == 1


@pytest.mark.parametrize("answer", [
    {"kind": "subject_not_in_period", "subject": "History", "period": 3},    # unknown subject
    {"kind": "subject_not_in_period", "subject": "PE", "period": 9},         # period out of range
    {"kind": "teacher_unavailable", "teacher_id": 99999, "day": "Sunday", "period": 1},  # invented teacher
    {"kind": "teacher_unavailable", "teacher_id": 1, "day": "Friday", "period": 1},      # not a school day
    {"kind": "pin_lesson", "class": "9/9", "subject": "PE", "day": "Sunday", "period": 1},
    {"kind": "delete_everything"},
    {"error": "That mentions several days."},
])
def test_bad_answers_are_rejected_with_422(api, ai, answer):
    ai.answer = answer
    r = parse(api, "x")
    assert r.status_code == 422 and r.json()["error"] in ("cannot_parse", "invalid_rule")


def test_garbage_reply_is_503(api, ai):
    ai.answer = "I think you want PE moved."
    assert parse(api, "x").status_code == 503


def test_prompt_has_only_short_teacher_names(api, ai):
    api.db.execute("INSERT INTO teachers (name, subject_id) VALUES ('Sara Khaled Mutairi', 1)")
    api.db.commit()
    ai.answer = {"error": "unclear"}
    parse(api, "something")
    system = ai.sent[-1][0]["content"]
    assert "Sara M." in system and "Khaled" not in system and "Mutairi" not in system


def test_empty_text_is_422(api, ai):
    assert parse(api, "   ").status_code == 422


# ---------- "move a lesson" (becomes a pin_lesson at the target slot) ----------

@pytest.fixture()
def timetable(api):
    api.db.execute("DELETE FROM lessons")
    cls = api.db.execute("SELECT id FROM classes WHERE name = '1/1'").fetchone()[0]  # 1/1 has Math on Sunday period 1
    tid = api.db.execute("SELECT id FROM teachers WHERE subject_id = 4 LIMIT 1").fetchone()[0]
    api.db.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, 4, 0, 1)", (cls, tid))
    api.db.commit()
    return cls


def test_move_lesson_becomes_pin_at_target(api, ai, timetable):
    ai.answer = {"kind": "move_lesson", "class": "1/1", "from_day": "Sunday", "from_period": 1,
                 "to_day": "Monday", "to_period": 1}
    r = parse(api, "Move class 1/1 Sunday period 1 to Monday period 1")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "pin_lesson"
    assert body["params"] == {"class_id": timetable, "subject_id": 4, "day": 1, "period": 1}
    assert "Math" in body["explanation"] and "Sunday period 1" in body["explanation"] and "Monday period 1" in body["explanation"]


def test_move_lesson_arabic_values(api, ai, timetable):
    ai.answer = {"kind": "move_lesson", "class": "١/١", "from_day": "الأحد", "from_period": "١",
                 "to_day": "الاثنين", "to_period": "٢"}
    r = parse(api, "انقل حصة الصف 1/1 من الأحد الحصة 1 إلى الاثنين الحصة 2")
    assert r.status_code == 200 and r.json()["params"]["day"] == 1 and r.json()["params"]["period"] == 2
    assert "الرياضيات" in r.json()["explanation"]


def test_move_lesson_errors(api, ai, timetable):
    base = {"kind": "move_lesson", "class": "1/1", "from_day": "Sunday", "from_period": 1, "to_day": "Monday", "to_period": 1}
    ai.answer = {**base, "from_period": 4}  # class has no lesson there
    assert parse(api, "x").status_code == 422
    ai.answer = {**base, "to_day": "Sunday", "to_period": 1}  # same slot
    assert parse(api, "x").status_code == 422
    ai.answer = {**base, "to_day": "Friday"}
    assert parse(api, "x").status_code == 422
    api.db.execute("DELETE FROM lessons")
    api.db.commit()
    ai.answer = base
    r = parse(api, "x")
    assert r.status_code == 409 and r.json()["error"] == "no_timetable"
