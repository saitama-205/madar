"""GET / POST / DELETE /api/rules, and that saved rules really change the generated timetable."""
import pytest

from test_solver import check_timetable, one, subject_id


def post(api, kind, params, source_text=None):
    body = {"kind": kind, "params": params}
    if source_text is not None:
        body["source_text"] = source_text
    return api.post("/api/rules", json=body)


# ---------- GET ----------

def test_list_has_the_seeded_rules_with_params_as_objects(api):
    r = api.get("/api/rules")
    assert r.status_code == 200
    rules = r.json()
    assert len(rules) == 80
    assert set(rules[0]) == {"id", "kind", "params", "source_text"}
    assert rules[0]["kind"] == "teacher_unavailable"
    assert set(rules[0]["params"]) == {"teacher_id", "day", "period"}
    assert [x["id"] for x in rules] == sorted(x["id"] for x in rules)


# ---------- POST: success ----------

def test_create_each_kind(api):
    pe, math = subject_id(api.db, "PE"), subject_id(api.db, "Math")
    cases = [
        ("subject_not_in_period", {"subject_id": pe, "period": 7}, "PE never in period 7"),
        ("teacher_unavailable", {"teacher_id": 1, "day": 2, "period": 3}, None),
        ("pin_lesson", {"class_id": 1, "subject_id": math, "day": 4, "period": 1}, "  Math first on Thursday  "),
    ]
    for kind, params, text in cases:
        r = post(api, kind, params, text)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["kind"] == kind and body["params"] == params and isinstance(body["id"], int)
        assert body["source_text"] == (text.strip() if text else None)
    assert len(api.get("/api/rules").json()) == 83
    assert api.get("/api/rules").json()[-1]["source_text"] == "Math first on Thursday"


# ---------- POST: validation ----------

BAD = [
    ("unknown kind", "teleport", {"x": 1}),
    ("missing setting", "subject_not_in_period", {"subject_id": 1}),
    ("typo / extra setting", "subject_not_in_period", {"subject_id": 1, "period": 7, "perod": 3}),
    ("period too big", "subject_not_in_period", {"subject_id": 1, "period": 8}),
    ("period zero", "subject_not_in_period", {"subject_id": 1, "period": 0}),
    ("day too big", "teacher_unavailable", {"teacher_id": 1, "day": 5, "period": 1}),
    ("number as text", "teacher_unavailable", {"teacher_id": "1", "day": 0, "period": 1}),
    ("decimal", "teacher_unavailable", {"teacher_id": 1, "day": 0, "period": 1.5}),
    ("true instead of number", "teacher_unavailable", {"teacher_id": True, "day": 0, "period": 1}),
    ("unknown subject", "subject_not_in_period", {"subject_id": 999, "period": 1}),
    ("unknown teacher", "teacher_unavailable", {"teacher_id": 999, "day": 0, "period": 1}),
    ("unknown class", "pin_lesson", {"class_id": 999, "subject_id": 1, "day": 0, "period": 1}),
]


@pytest.mark.parametrize("label,kind,params", BAD, ids=[b[0] for b in BAD])
def test_invalid_rules_are_rejected_and_not_saved(api, label, kind, params):
    r = post(api, kind, params)
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "invalid_rule"
    assert isinstance(r.json()["message"], str) and len(r.json()["message"]) > 10
    assert len(api.get("/api/rules").json()) == 80


def test_error_messages_are_readable(api):
    assert "'period' must be 1 to 7" in post(api, "subject_not_in_period", {"subject_id": 1, "period": 9}).json()["message"]
    assert "'period' is missing" in post(api, "subject_not_in_period", {"subject_id": 1}).json()["message"]
    assert "unknown rule kind" in post(api, "teleport", {}).json()["message"]


def test_bad_request_shapes(api):
    assert api.post("/api/rules", json={}).status_code == 422
    assert api.post("/api/rules", json={"kind": "pin_lesson"}).status_code == 422
    assert api.post("/api/rules", json={"kind": "pin_lesson", "params": [1, 2]}).status_code == 422


def test_cannot_pin_a_subject_the_class_does_not_have(api):
    db = api.db
    db.execute("DELETE FROM subject_hours WHERE grade = 1 AND subject_id = ?", (subject_id(db, "Music"),))
    db.commit()
    r = post(api, "pin_lesson", {"class_id": 1, "subject_id": subject_id(db, "Music"), "day": 0, "period": 1})
    assert r.status_code == 422 and "nothing to pin" in r.json()["message"]


def test_duplicate_rule_is_a_conflict(api):
    pe = subject_id(api.db, "PE")
    assert post(api, "subject_not_in_period", {"subject_id": pe, "period": 7}).status_code == 201
    r = post(api, "subject_not_in_period", {"subject_id": pe, "period": 7})
    assert r.status_code == 409 and r.json()["error"] == "duplicate_rule"
    # also detected against a seeded rule, whatever order its keys were stored in
    seeded = api.get("/api/rules").json()[0]
    assert post(api, seeded["kind"], seeded["params"]).status_code == 409


# ---------- DELETE ----------

def test_delete_a_rule(api):
    rule_id = api.get("/api/rules").json()[0]["id"]
    r = api.delete(f"/api/rules/{rule_id}")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert rule_id not in [x["id"] for x in api.get("/api/rules").json()]
    assert len(api.get("/api/rules").json()) == 79


def test_delete_unknown_rule(api):
    r = api.delete("/api/rules/99999")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert api.delete("/api/rules/abc").status_code == 422


# ---------- the whole flow: add a rule, regenerate, the timetable obeys it ----------

def test_a_saved_rule_is_obeyed_after_regenerating_and_gone_after_delete(api):
    db = api.db
    pe = subject_id(db, "PE")
    api.post("/api/timetable/generate")
    # the period where PE is most common right now: forbidding it is a real change, not a no-op
    period = one(db, "SELECT period FROM lessons WHERE subject_id = ? GROUP BY period ORDER BY COUNT(*) DESC LIMIT 1", pe)
    before = one(db, "SELECT COUNT(*) FROM lessons WHERE subject_id = ? AND period = ?", pe, period)
    assert before > 0

    rule = post(api, "subject_not_in_period", {"subject_id": pe, "period": period}, "PE never in that period").json()
    assert one(db, "SELECT COUNT(*) FROM lessons WHERE subject_id = ? AND period = ?", pe, period) == before  # not regenerated yet
    assert api.post("/api/timetable/generate").status_code == 200
    check_timetable(db)  # checks every saved rule, including the new one
    assert one(db, "SELECT COUNT(*) FROM lessons WHERE subject_id = ? AND period = ?", pe, period) == 0

    assert api.delete(f"/api/rules/{rule['id']}").status_code == 200
    assert api.post("/api/timetable/generate").status_code == 200
    check_timetable(db)


def test_a_rule_that_makes_the_timetable_impossible_is_reported_by_generate(api):
    """POST does not try to solve; Generate reports the conflict and keeps the old timetable."""
    db = api.db
    api.post("/api/timetable/generate")
    row = db.execute("""SELECT t.subject_id, MIN(tc.class_id) AS a, MAX(tc.class_id) AS b FROM teachers t
                        JOIN teacher_classes tc ON tc.teacher_id = t.id GROUP BY t.id HAVING COUNT(*) >= 2 LIMIT 1""").fetchone()
    for cls in (row["a"], row["b"]):
        assert post(api, "pin_lesson", {"class_id": cls, "subject_id": row["subject_id"], "day": 2, "period": 4}).status_code == 201
    r = api.post("/api/timetable/generate")
    assert r.status_code == 409 and r.json()["error"] == "infeasible"
    assert one(db, "SELECT COUNT(*) FROM lessons") == 700
