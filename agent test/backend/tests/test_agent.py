"""The assistant (ai/agent.py) with a scripted fake model: no network, no real key."""
import json
import re

import pytest

from ai import agent, llm
from errors import ApiError


@pytest.fixture()
def model(monkeypatch):
    """box.script = list of assistant messages the fake model sends back, in order. box.sent = payloads it received."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    box = type("Box", (), {"script": [], "sent": []})()

    def fake_send(payload, headers):
        box.sent.append(json.loads(json.dumps(payload)))
        if not box.script:
            pytest.fail("the agent asked the model more times than the test expected")
        msg = box.script.pop(0)
        if isinstance(msg, tuple):  # (status, body) for error tests
            return msg
        return 200, json.dumps({"choices": [{"message": msg}]})

    monkeypatch.setattr(llm, "_send", fake_send)
    return box


_n = iter(range(10_000))


def tool(fn_name, /, **args):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"call_{next(_n)}", "type": "function", "function": {"name": fn_name, "arguments": json.dumps(args)}}]}


def say(text):
    return {"role": "assistant", "content": text}


def tool_results(payload):
    return [json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool"]


def counts(db):
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("teachers", "teacher_classes", "rules", "lessons")}


def first_teacher(db, subject):
    return db.execute("""SELECT t.id, t.name FROM teachers t JOIN subjects s ON s.id = t.subject_id
                         JOIN teacher_classes tc ON tc.teacher_id = t.id WHERE s.name = ? ORDER BY t.id LIMIT 1""",
                      (subject,)).fetchone()


def test_no_key_is_503(seeded, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(llm, "ENV_FILE", llm.ENV_FILE.with_name("nope.env"))
    monkeypatch.setattr(llm, "_send", lambda *a: pytest.fail("must not call the network"))
    with pytest.raises(ApiError) as e:
        agent.run_agent(seeded, "hello")
    assert e.value.status == 503 and e.value.error == "ai_unavailable"


def test_teacher_leaves_flow_proposes_a_replacement_and_saves_nothing(seeded, model):
    t = first_teacher(seeded, "Arabic")
    class_ids = [r["class_id"] for r in seeded.execute("SELECT class_id FROM teacher_classes WHERE teacher_id = ?", (t["id"],))]
    arabic = seeded.execute("SELECT id FROM subjects WHERE name = 'Arabic'").fetchone()["id"]
    before = counts(seeded)
    model.script = [
        tool("find_teachers", subject="Arabic"),
        tool("propose_new_teacher", name="Huda A.", subject_id=arabic, class_ids=class_ids, reason="replaces a teacher who left"),
        say("I prepared P1: Huda A. takes over the Arabic classes. Approve it, then press Generate."),
    ]
    out = agent.run_agent(seeded, f"{t['name']} has left the school. Huda A. replaces her.")

    assert out["reply"].startswith("I prepared P1")
    (p,) = out["proposals"]
    assert p["id"] == "P1" and p["type"] == "teacher"
    assert p["request"] == {"method": "POST", "path": "/api/teachers",
                           "body": {"name": "Huda A.", "subject_id": arabic, "class_ids": class_ids}}
    assert any(t["name"] in i["text"] for i in p["impact"])          # whose classes move: computed by Python
    assert [s["tool"] for s in out["steps"]] == ["find_teachers", "propose_new_teacher"]
    found = tool_results(model.sent[1])[0]["teachers"]
    assert {x["subject"] for x in found} == {"Arabic"}
    assert counts(seeded) == before                                    # nothing written


def test_rule_proposals_are_validated_like_the_rules_endpoint(seeded, model):
    pe = seeded.execute("SELECT id FROM subjects WHERE name = 'PE'").fetchone()["id"]
    saved = seeded.execute("SELECT params FROM rules WHERE kind = 'teacher_unavailable' LIMIT 1").fetchone()
    dup = json.loads(saved["params"])
    model.script = [
        tool("propose_rule", kind="subject_not_in_period", subject_id=pe, period=9),        # bad period
        tool("propose_rule", kind="teacher_unavailable", **dup),                           # already saved
        tool("propose_rule", kind="subject_not_in_period", subject_id=pe, period=7),        # fine
        tool("propose_rule", kind="subject_not_in_period", subject_id=pe, period=7),        # proposed twice
        say("P1 keeps PE out of period 7."),
    ]
    before = counts(seeded)
    out = agent.run_agent(seeded, "PE never in period 7")
    results = tool_results(model.sent[-1])
    assert results[0]["ok"] is False and "period" in results[0]["error"]
    assert results[1] == {"ok": False, "error": "That rule is already saved."}
    assert results[2]["ok"] is True and results[2]["id"] == "P1"
    assert results[3]["id"] == "P1" and results[3]["note"] == "Already proposed."
    (p,) = out["proposals"]
    assert p["request"]["body"]["kind"] == "subject_not_in_period"
    assert p["request"]["body"]["params"] == {"subject_id": pe, "period": 7}
    assert p["description"] == "PE will never be in period 7."
    assert counts(seeded) == before


def test_teacher_unavailable_impact_reports_load_from_python(seeded, model):
    t = first_teacher(seeded, "Math")
    model.script = [tool("propose_rule", kind="teacher_unavailable", teacher_id=t["id"], day=2, period=3), say("ok")]
    out = agent.run_agent(seeded, "x")
    need = agent._weekly_need(seeded, t["id"])
    free = 35 - len(agent._unavailable(seeded, t["id"]) | {(2, 3)})
    assert any(f"{need} lessons a week, {free} free slots" in i["text"] for i in out["proposals"][0]["impact"])


def test_unknown_tool_and_bad_arguments_are_reported_back_not_crashing(seeded, model):
    bad_json = tool("list_rules")
    bad_json["tool_calls"][0]["function"]["arguments"] = "{nope"
    model.script = [tool("delete_everything"), bad_json, tool("list_rules", colour="red"), say("done")]
    out = agent.run_agent(seeded, "x")
    errors = [r["error"] for r in tool_results(model.sent[-1])]
    assert "There is no tool called delete_everything." in errors
    assert "The tool arguments were not valid JSON." in errors
    assert any(e.startswith("Wrong arguments for list_rules") for e in errors)
    assert out["reply"] == "done"


def test_last_round_must_answer_in_words(seeded, model):
    model.script = [tool("list_rules") for _ in range(agent.MAX_STEPS - 1)] + [say("Here is what I found.")]
    out = agent.run_agent(seeded, "x")
    assert [p["tool_choice"] for p in model.sent] == ["auto"] * (agent.MAX_STEPS - 1) + ["none"]
    assert out["reply"] == "Here is what I found." and len(out["steps"]) == agent.MAX_STEPS - 1


def test_ai_failing_half_way_still_returns_the_proposals(seeded, model):
    pe = seeded.execute("SELECT id FROM subjects WHERE name = 'PE'").fetchone()["id"]
    model.script = [tool("propose_rule", kind="subject_not_in_period", subject_id=pe, period=7), (500, "boom")]
    out = agent.run_agent(seeded, "x")
    assert len(out["proposals"]) == 1 and "couldn't finish" in out["reply"]


def test_only_short_teacher_names_reach_the_ai(seeded, model):
    t = first_teacher(seeded, "Science")
    seeded.execute("UPDATE teachers SET name = ? WHERE id = ?", ("نورة المليفي", t["id"]))
    model.script = [tool("find_teachers", name="نورة"), say("ok")]
    agent.run_agent(seeded, "Is نورة المليفي free?")
    sent = json.dumps(model.sent, ensure_ascii=False)
    assert "المليفي" not in sent and "نورة م." in sent


def test_arabic_request_gets_arabic_descriptions(seeded, model):
    pe = seeded.execute("SELECT id FROM subjects WHERE name = 'PE'").fetchone()["id"]
    model.script = [tool("propose_rule", kind="subject_not_in_period", subject_id=pe, period=7), say("تم تجهيز P1.")]
    out = agent.run_agent(seeded, "التربية البدنية ليست في الحصة 7")
    assert "الحصة 7" in out["proposals"][0]["description"]
    assert "Arabic" in model.sent[0]["messages"][0]["content"]


def test_endpoint_shape(request, model):
    pytest.importorskip("fastapi.testclient")
    api = request.getfixturevalue("api")
    model.script = [say("Hello! What would you like to change?")]
    r = api.post("/api/agent", json={"message": "hi", "language": "en"})
    assert r.status_code == 200
    assert r.json() == {"reply": "Hello! What would you like to change?", "proposals": [], "steps": []}
    assert api.post("/api/agent", json={"message": ""}).status_code == 422


def test_timetable_and_cover_tools_read_saved_lessons(seeded, model):
    t = first_teacher(seeded, "English")
    cid = seeded.execute("SELECT class_id FROM teacher_classes WHERE teacher_id = ? LIMIT 1", (t["id"],)).fetchone()[0]
    sid = seeded.execute("SELECT subject_id FROM teachers WHERE id = ?", (t["id"],)).fetchone()[0]
    other = seeded.execute("SELECT id FROM teachers WHERE subject_id = ? AND id != ? LIMIT 1", (sid, t["id"])).fetchone()[0]
    with seeded:
        seeded.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, 1, 2)", (cid, t["id"], sid))
        seeded.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, 1, 3)", (cid, other, sid))
    model.script = [tool("get_timetable", teacher_id=t["id"]), tool("find_cover", teacher_id=t["id"], day=1), say("ok")]
    out = agent.run_agent(seeded, "x")
    week, cover = tool_results(model.sent[-1])
    assert week["lessons"][0]["day"] == 1 and week["lessons"][0]["period"] == 2 and week["per_day"] == [0, 1, 0, 0, 0]
    assert cover["lessons"][0]["period"] == 2
    subs = cover["lessons"][0]["substitutes"]
    assert len(subs) == 3 and all(x["reason"] == "same_subject_free" and x["day_load"] == 0 for x in subs)
    assert t["id"] not in {x["teacher_id"] for x in subs} and other not in {x["teacher_id"] for x in subs}  # busier that day
    assert out["proposals"] == [] and [s["tool"] for s in out["steps"]] == ["get_timetable", "find_cover"]


def test_absence_given_only_as_a_time(seeded, model):
    """'Class X has no teacher on Monday period 2': read the slot, then who is free (same subject first)."""
    rows = seeded.execute("""SELECT tc.class_id, t.id AS tid, t.subject_id FROM teacher_classes tc JOIN teachers t ON t.id = tc.teacher_id
                             JOIN subjects s ON s.id = t.subject_id WHERE s.name = 'Math' ORDER BY t.id LIMIT 2""").fetchall()
    (c1, t1, sid), (c2, t2, _) = rows
    same = [r["id"] for r in seeded.execute("SELECT id FROM teachers WHERE subject_id = ? AND id NOT IN (?, ?)", (sid, t1, t2))]
    with seeded:
        seeded.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, 1, 2)", (c1, t1, sid))
        seeded.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, 1, 4)", (c2, t2, sid))
        seeded.execute("INSERT INTO rules (kind, params, source_text) VALUES ('teacher_unavailable', ?, NULL)",
                       (json.dumps({"teacher_id": same[0], "day": 1, "period": 2}),))
    model.script = [tool("get_slot", day=1, period=2, class_id=c1), tool("who_is_free", day=1, period=2, subject_id=sid),
                    tool("get_slot", day=1, period=9), say("ok")]
    before = counts(seeded)
    out = agent.run_agent(seeded, "Class has no teacher on Monday period 2")
    slot, free, bad = tool_results(model.sent[-1])
    assert [l["teacher_id"] for l in slot["lessons"]] == [t1]
    ids = [x["teacher_id"] for x in free["teachers"]]
    assert t1 not in ids                      # busy in that slot
    assert same[0] not in ids                 # marked unavailable then
    assert free["teachers"][0]["same_subject"] is True and free["teachers"][0]["lessons_that_day"] == 0
    assert ids.index(t2) > ids.index(free["teachers"][0]["teacher_id"])  # t2 has a lesson that day, so ranks lower
    assert bad["ok"] is False
    assert out["proposals"] == [] and counts(seeded) == before
    assert out["steps"][1]["summary"].startswith("Found ") and "Monday, period 2" in out["steps"][1]["summary"]


def test_every_seeded_teacher_has_a_unique_english_name(seeded):
    from names_en import english_name
    names = [r["name"] for r in seeded.execute("SELECT name FROM teachers")]
    en = [english_name(n) for n in names]
    assert None not in en and len(set(en)) == len(names) == 79
    assert all(re.fullmatch(r"[A-Z][a-z]+( (Sh|Kh|Gh|Dh|Th|[A-Z])\.)?( \(\d\))?", e) for e in en)
    assert english_name("فاطمة ج.") == "Fatima J." and english_name("Sara K.") == "Sara K."
    assert english_name("نورة المليفي") == "Noura M."          # full names (owner's local data) map through the short name


def test_find_teachers_matches_english_spellings(seeded, model):
    model.script = [tool("find_teachers", name="Fatima"), tool("find_teachers", name="fatima m"), say("ok")]
    agent.run_agent(seeded, "Fatima")
    every, just_m = tool_results(model.sent[-1])
    assert len(every["teachers"]) == 6 and all(t["name_en"].startswith("Fatima") for t in every["teachers"])
    assert {t["name_en"] for t in just_m["teachers"]} == {"Fatima M.", "Fatima M. (2)", "Fatima M. (3)"}


def test_teachers_endpoint_includes_english_names(request):
    pytest.importorskip("fastapi.testclient")
    api = request.getfixturevalue("api")
    teachers = api.get("/api/teachers").json()
    assert all(t["name_en"] for t in teachers)
    new = api.post("/api/teachers", json={"name": "Huda A.", "subject_id": 1, "class_ids": []}).json()
    assert new["name_en"] == "Huda A."


def test_english_answers_use_english_names_and_arabic_answers_arabic(seeded, model):
    t = first_teacher(seeded, "Math")
    model.script = [tool("propose_rule", kind="teacher_unavailable", teacher_id=t["id"], day=0, period=1), say("ok")]
    en = agent.run_agent(seeded, "she can't teach Sunday period 1")["proposals"][0]["description"]
    model.script = [tool("propose_rule", kind="teacher_unavailable", teacher_id=t["id"], day=0, period=2), say("تم")]
    ar = agent.run_agent(seeded, "لا تستطيع التدريس يوم الأحد الحصة 2")["proposals"][0]["description"]
    from names_en import english_name
    assert english_name(t["name"]) in en and t["name"] not in en
    assert t["name"] in ar
