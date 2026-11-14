import json

import pytest

from ai import llm


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    """One real generated timetable shared by the tests in this file (solving takes several seconds)."""
    from fastapi.testclient import TestClient
    from main import create_app
    with pytest.MonkeyPatch.context() as mp:  # module scope: the built-in monkeypatch fixture is per test
        mp.setenv("MADAR_DB", str(tmp_path_factory.mktemp("an") / "an.db"))
        mp.setenv("MADAR_AUTO_GENERATE", "0")
        with TestClient(create_app(frontend_dir=tmp_path_factory.mktemp("nofe"))) as client:
            assert client.post("/api/timetable/generate").status_code == 200
            yield client


@pytest.fixture()
def no_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(llm, "ENV_FILE", llm.ENV_FILE.with_name("nope.env"))


def test_no_timetable_is_409(api):
    r = api.get("/api/analytics")
    assert r.status_code == 409 and r.json()["error"] == "no_timetable"
    assert api.post("/api/analytics/insights", json={}).status_code == 409


def test_metrics_shape_and_numbers(generated):
    m = generated.get("/api/analytics").json()
    assert m["rule_check"] == {"ok": True, "violations": []}
    assert len(m["class_load"]) == 20 and all(c["per_day"] == [7] * 5 for c in m["class_load"])
    assert sum(t["per_week"] for t in m["teacher_load"]) == 20 * 35
    assert all(sum(t["per_day"]) == t["per_week"] and len(t["per_day"]) == 5 for t in m["teacher_load"])
    assert set(m["hard_subjects_by_period"]) == {"Arabic", "English", "Math", "Science"}
    assert all(len(v) == 7 for v in m["hard_subjects_by_period"].values())
    for g in m["teacher_gaps"]:
        assert g["gap_periods"] > 0 and 0 <= g["day"] <= 4


def test_hard_subject_totals_match_study_plan(generated):
    m = generated.get("/api/analytics").json()
    # Grades 1-3 have 5 Math lessons, grades 4-5 have 6; four sections per grade.
    assert sum(m["hard_subjects_by_period"]["Math"]) == 4 * (5 * 3 + 6 * 2)


def test_rule_check_detects_a_broken_rule(generated):
    from database.db import get_connection
    conn = get_connection()
    try:
        lesson = conn.execute("SELECT subject_id, period FROM lessons LIMIT 1").fetchone()
        conn.execute("INSERT INTO rules (kind, params, source_text) VALUES ('subject_not_in_period', ?, 'test')",
                     (json.dumps({"subject_id": lesson["subject_id"], "period": lesson["period"]}),))
        conn.commit()
        m = generated.get("/api/analytics").json()
        assert m["rule_check"]["ok"] is False and "never" in m["rule_check"]["violations"][0]
        conn.execute("DELETE FROM rules WHERE source_text = 'test'")
        conn.commit()
    finally:
        conn.close()
    assert generated.get("/api/analytics").json()["rule_check"]["ok"] is True


def test_insights_without_key_is_503(generated, no_key):
    r = generated.post("/api/analytics/insights", json={"language": "en"})
    assert r.status_code == 503 and r.json()["error"] == "ai_unavailable"


def _fake(monkeypatch, answer, sent):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    def send(payload, headers):
        sent.append(payload["messages"])
        return 200, json.dumps({"choices": [{"message": {"content": text}}]})
    monkeypatch.setattr(llm, "_send", send)


def test_insights_happy_path_sends_only_metrics_and_short_names(generated, monkeypatch):
    from database.db import get_connection
    conn = get_connection()
    conn.execute("UPDATE teachers SET name = 'Sara Khaled Mutairi' WHERE id = 1")
    conn.commit()
    conn.close()
    sent = []
    _fake(monkeypatch, {"summary": "The load is balanced across 20 classes.", "recommendations": ["Review teachers with gaps."]}, sent)
    r = generated.post("/api/analytics/insights", json={"language": "ar"})
    assert r.status_code == 200 and r.json()["recommendations"] == ["Review teachers with gaps."]
    system, user = sent[0][0]["content"], sent[0][1]["content"]
    assert "Arabic" in system and user.startswith("METRICS:")
    assert "Sara M." in user and "Khaled" not in user and "Mutairi" not in user


def test_insights_rejects_invented_numbers(generated, monkeypatch):
    sent = []
    _fake(monkeypatch, {"summary": "Exactly 987654 lessons were scheduled.", "recommendations": []}, sent)
    r = generated.post("/api/analytics/insights", json={})
    assert r.status_code == 502 and r.json()["error"] == "ai_bad_answer" and len(sent) == 2  # asked once more


def test_insights_garbage_is_503(generated, monkeypatch):
    _fake(monkeypatch, "sorry, no", [])
    assert generated.post("/api/analytics/insights", json={}).status_code == 503


def test_insights_bad_language_is_422(generated):
    assert generated.post("/api/analytics/insights", json={"language": "fr"}).status_code == 422
