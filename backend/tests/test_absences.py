import json

import pytest

from ai import llm


def teachers_of(api, subject_id):
    return [t["id"] for t in api.get("/api/teachers").json() if t["subject_id"] == subject_id]


def lesson(api, class_id, teacher_id, subject_id, day, period):
    api.db.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, ?, ?)",
                   (class_id, teacher_id, subject_id, day, period))
    api.db.commit()


@pytest.fixture()
def scene(api):
    """Absent math teacher A has Monday period 2 with class 1. Same-subject math teachers B (busy then) and C (free),
    and other-subject teacher D (free, lighter day) and E (free, heavier day)."""
    api.db.execute("DELETE FROM lessons")
    api.db.execute("DELETE FROM rules WHERE kind = 'teacher_unavailable'")  # keep the scene free of seed rules
    api.db.commit()
    math = teachers_of(api, 4)
    english = teachers_of(api, 3)
    a, b, c = math[:3]
    d, e = english[:2]
    cls = api.get("/api/classes").json()
    lesson(api, cls[0]["id"], a, 4, 1, 2)
    lesson(api, cls[1]["id"], b, 4, 1, 2)      # B busy in that slot
    lesson(api, cls[2]["id"], c, 4, 1, 3)      # C free in period 2, one lesson that day
    lesson(api, cls[3]["id"], e, 3, 1, 5)      # E: one lesson
    lesson(api, cls[4]["id"], e, 3, 1, 6)      # E: two lessons
    for i, other in enumerate(m for m in math if m not in (a, b, c)):
        lesson(api, cls[6 + i]["id"], other, 4, 1, 2)  # every other math teacher is busy too, so C is the only one
    return dict(a=a, b=b, c=c, d=d, e=e, cls=cls)


def test_ranking_same_subject_first_then_lighter_day(api, scene):
    r = api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1})
    assert r.status_code == 200
    (item,) = r.json()
    assert (item["day"], item["period"], item["class"], item["subject"]) == (1, 2, scene["cls"][0]["name"], "Math")
    subs = item["substitutes"]
    assert len(subs) == 3 and scene["b"] not in [s["teacher_id"] for s in subs]
    assert subs[0]["teacher_id"] == scene["c"] and subs[0]["reason"] == "same_subject_free"
    assert [s["reason"] for s in subs[1:]] == ["free_only", "free_only"]
    assert subs[1]["day_load"] <= subs[2]["day_load"]
    assert subs[0]["name"]  # contract shape: teacher_id + name


def test_teacher_with_unavailable_rule_is_skipped(api, scene):
    api.post("/api/rules", json={"kind": "teacher_unavailable", "params": {"teacher_id": scene["c"], "day": 1, "period": 2}})
    subs = api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1}).json()[0]["substitutes"]
    assert scene["c"] not in [s["teacher_id"] for s in subs]


def test_no_lessons_that_day_gives_empty_list(api, scene):
    assert api.post("/api/absences", json={"teacher_id": scene["a"], "day": 3}).json() == []


def test_errors(api, scene):
    assert api.post("/api/absences", json={"teacher_id": 99999, "day": 1}).status_code == 404
    assert api.post("/api/absences", json={"teacher_id": scene["a"], "day": 5}).status_code == 422
    api.db.execute("DELETE FROM lessons")
    api.db.commit()
    r = api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1})
    assert r.status_code == 409 and r.json()["error"] == "no_timetable"


def test_no_key_uses_template_explanation(api, scene, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(llm, "ENV_FILE", llm.ENV_FILE.with_name("nope.env"))
    item = api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1}).json()[0]
    assert item["explanation_source"] == "template" and "period 2" in item["explanation"]


def test_ai_sentence_used_and_prompt_has_short_names(api, scene, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    api.db.execute("UPDATE teachers SET name = 'Sara Khaled Mutairi' WHERE id = ?", (scene["a"],))
    api.db.execute("UPDATE teachers SET name = 'Huda Salem Rashidi' WHERE id = ?", (scene["c"],))
    api.db.commit()
    sent = []

    def fake(payload, headers):
        sent.append(payload["messages"][0]["content"])
        return 200, json.dumps({"choices": [{"message": {"content": "Huda R. teaches Math too."}}]})

    monkeypatch.setattr(llm, "_send", fake)
    item = api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1}).json()[0]
    assert item["explanation"] == "Huda R. teaches Math too." and item["explanation_source"] == "ai"
    prompt = sent[0]
    assert "Sara M." in prompt and "Huda R." in prompt
    assert "Khaled" not in prompt and "Mutairi" not in prompt and "Salem" not in prompt and "Rashidi" not in prompt


def test_ai_failure_falls_back_and_stops_calling(api, scene, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    # a second lesson for A so there are two affected lessons
    lesson(api, scene["cls"][5]["id"], scene["a"], 4, 1, 4)
    calls = []
    monkeypatch.setattr(llm, "_send", lambda *a: (calls.append(1), (500, "boom"))[1])
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    items = api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1}).json()
    assert len(items) == 2 and all(i["explanation_source"] == "template" for i in items)
    assert len(calls) == 1


def test_language_ar_template_when_no_key(api, scene, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(llm, "ENV_FILE", llm.ENV_FILE.with_name("nope.env"))
    item = api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1, "language": "ar"}).json()[0]
    assert item["explanation_source"] == "template"
    assert "الحصة 2" in item["explanation"] and "الرياضيات" in item["explanation"]


def test_language_is_passed_to_the_ai(api, scene, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    sent = []

    def fake(payload, headers):
        sent.append(payload["messages"][0]["content"])
        return 200, json.dumps({"choices": [{"message": {"content": "جملة"}}]})

    monkeypatch.setattr(llm, "_send", fake)
    api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1, "language": "ar"})
    api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1})
    assert "Write it in Arabic" in sent[0] and "Write it in English" in sent[1]


def test_bad_language_is_422(api, scene):
    assert api.post("/api/absences", json={"teacher_id": scene["a"], "day": 1, "language": "fr"}).status_code == 422
