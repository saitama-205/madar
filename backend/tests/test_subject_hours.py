import pytest

import regen


def hours(api, grade):
    return {r["subject_id"]: r["per_week"] for r in api.get("/api/subject-hours").json() if r["grade"] == grade}


def test_get_lists_every_grade_and_subject(api):
    rows = api.get("/api/subject-hours").json()
    assert len(rows) == 50 and set(rows[0]) == {"grade", "subject_id", "per_week"}


def test_put_moves_hours_and_keeps_the_total(api):
    before = hours(api, 1)
    # Computer 1 -> 2 and PE 4 -> 3 (ids by subject order in the seed: find them)
    ids = {s["name"]: s["id"] for s in api.get("/api/subjects").json()}
    r = api.put("/api/subject-hours/1", json={"hours": {str(ids["Computer"]): before[ids["Computer"]] + 1,
                                                        str(ids["PE"]): before[ids["PE"]] - 1}})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["grade"] == 1 and sum(body["hours"].values()) == 35
    assert set(body) >= {"generated", "violations", "warnings"}
    assert hours(api, 1)[ids["Computer"]] == before[ids["Computer"]] + 1 and hours(api, 1)[ids["PE"]] == before[ids["PE"]] - 1
    assert sum(hours(api, 1).values()) == 35


@pytest.mark.parametrize("payload", [
    {"hours": {"1": 10}},                      # total no longer 35
    {"hours": {"999": 5}},                     # unknown subject
    {"hours": {"1": -1}}, {"hours": {"1": 40}}, {"hours": {"1": "4"}}, {"hours": {"1": 4.5}}, {"hours": {"1": True}},
    {"hours": {"abc": 4}}, {"hours": {}},
])
def test_put_rejects_bad_hours_and_changes_nothing(api, payload):
    before = api.get("/api/subject-hours").json()
    r = api.put("/api/subject-hours/1", json=payload)
    assert r.status_code == 400 and r.json()["error"] == "invalid_hours" and r.json()["message"]
    assert api.get("/api/subject-hours").json() == before


def test_put_bad_grade(api):
    assert api.put("/api/subject-hours/9", json={"hours": {"1": 4}}).status_code == 400


def test_put_regenerates_automatically(api, monkeypatch):
    monkeypatch.setenv("MADAR_AUTO_REGENERATE", "1")
    calls = []
    monkeypatch.setattr(regen.solver, "generate_timetable", lambda db: calls.append(1) or {"lessons_count": 0, "seconds": 0, "warnings": ["w"]})
    ids = {s["name"]: s["id"] for s in api.get("/api/subjects").json()}
    base = hours(api, 1)
    r = api.put("/api/subject-hours/1", json={"hours": {str(ids["Computer"]): base[ids["Computer"]] + 1, str(ids["PE"]): base[ids["PE"]] - 1}})
    assert calls == [1] and r.json()["generated"] is True and r.json()["warnings"] == ["w"]
