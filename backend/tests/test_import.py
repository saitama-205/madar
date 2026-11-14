"""Excel import (one sheet: class, subject, teacher, hours_per_week): template, preview (saves nothing), confirm
(replaces everything, then regenerates), and the clear errors."""
import io
import json

import pytest
from openpyxl import Workbook, load_workbook

import regen
from database.seed import PUBLIC_DATA

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADER = ["class", "subject", "teacher", "hours_per_week"]


def make_workbook(rows, header=HEADER, title="Timetable data", extra_sheet=False):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(header)
    for row in rows:
        ws.append(row)
    if extra_sheet:
        wb.create_sheet("Other")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def seed_rows():
    """The whole real school (from the committed seed, shortened names) as upload rows."""
    d = json.loads(PUBLIC_DATA.read_text(encoding="utf-8"))
    names = {s["id"]: s["name"] for s in d["subjects"]}
    hours = {(h["grade"], h["subject"]): h["per_week"] for h in d["subject_hours"]}
    teacher = {}
    for t in d["teachers"]:
        for c in t["classes"]:
            teacher[c, t["subject"]] = t["name"]
    rows = []
    for c in d["classes"]:
        for s in d["subjects"]:
            h = hours.get((c["grade"], s["id"]), 0)
            if h:
                rows.append([c["name"], names[s["id"]], teacher.get((c["name"], s["id"]), ""), h])
    return rows


def upload(api, content, filename="school.xlsx"):
    return api.post("/api/import", files={"file": (filename, content, XLSX)})


def counts(db):
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("classes", "teachers", "subjects", "subject_hours", "teacher_classes", "rules", "lessons")}


# ---------- template ----------

def test_template_download(api):
    r = api.get("/api/import/template")
    assert r.status_code == 200 and "madar_template.xlsx" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Timetable data"]
    ws = wb["Timetable data"]
    assert [c.value for c in ws[1]] == ["class", "subject", "teacher", "hours_per_week"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(rows) == 20 * 10                                    # 20 classes x 10 subjects, one row each
    assert rows[0][0] == "1/1" and rows[0][3] > 0 and all(r[2] for r in rows)     # every row has a (shortened) teacher
    for c in {r[0] for r in rows}:
        assert sum(r[3] for r in rows if r[0] == c) == 35


def test_template_can_be_uploaded_as_is(api):
    body = upload(api, api.get("/api/import/template").content).json()
    assert len(body["rows"]) == 200 and body["warnings"] == []
    assert set(body["rows"][0]) == {"class", "subject", "teacher", "hours_per_week"}


# ---------- preview ----------

def test_preview_of_the_whole_school_saves_nothing(api):
    before = counts(api.db)
    r = upload(api, make_workbook(seed_rows()))
    assert r.status_code == 200
    assert len(r.json()["rows"]) == 200 and r.json()["warnings"] == []
    assert counts(api.db) == before


def test_columns_are_matched_ignoring_case_and_order(api):
    wb = make_workbook([[35, "Sara Khaled", "Math", "1/1"]], header=["Hours_Per_Week", "TEACHER", "Subject", "Class"])
    body = upload(api, wb).json()
    assert body["rows"] == [{"class": "1/1", "subject": "Math", "teacher": "Sara K.", "hours_per_week": 35}]


def test_full_names_are_shortened_in_the_preview(api):
    body = upload(api, make_workbook([["1/1", "Math", "Sara Khaled Mutairi", 35]])).json()
    assert body["rows"][0]["teacher"] == "Sara M."
    assert "Khaled" not in json.dumps(body) and "Mutairi" not in json.dumps(body)


def test_same_teacher_on_several_rows_stays_one_name_and_duplicates_are_told_apart(api):
    rows = [["1/1", "Math", "Sara Khaled Mutairi", 5], ["2/1", "Math", "Sara Khaled Mutairi", 5],
            ["3/1", "Math", "Sara Mohammed Matar", 5]]
    body = upload(api, make_workbook(rows)).json()
    assert [r["teacher"] for r in body["rows"]] == ["Sara M.", "Sara M.", "Sara M. (2)"]
    assert any('"Sara M. (2)"' in w for w in body["warnings"])


def test_arabic_subject_names_become_the_schools_subject(api):
    body = upload(api, make_workbook([["1/1", "الرياضيات", "Sara K", 35]])).json()
    assert body["rows"][0]["subject"] == "Math"


def test_data_problems_become_warnings_not_errors(api):
    rows = [["1/1", "Math", "", 30], ["nonsense", "Math", "X Y", 5], ["1/1", "Math", "X Y", 5], ["1/1", "", "X Y", 5], ["1/1", "Arabic", "X Y", 5]]
    body = upload(api, make_workbook(rows)).json()
    text = " ".join(body["warnings"])
    assert "nonsense" in text and "duplicate" in text and "subject is empty" in text
    assert "lessons per week in total" not in text           # 30 + 5 = 35, so the class total is fine
    assert "no teacher for Math" in text and len(body["rows"]) == 2


def test_class_total_and_grade_disagreement_warnings(api):
    rows = [["1/1", "Math", "A B", 5], ["1/1", "Arabic", "C D", 5], ["2/1", "Math", "A B", 6], ["2/1", "Arabic", "C D", 5]]
    text = " ".join(upload(api, make_workbook(rows)).json()["warnings"])
    assert "Class 1/1 has 10 lessons per week" in text and "classes disagree on the hours of Math" in text


@pytest.mark.parametrize("name,content,expected", [
    ("notes.txt", b"hello", "Only .xlsx"),
    ("school.xlsx", b"not a zip", "not a real .xlsx"),
    ("school.xlsx", b"", "empty"),
])
def test_wrong_files(api, name, content, expected):
    r = upload(api, content, name)
    assert r.status_code == 400 and r.json()["error"] == "invalid_file" and expected in r.json()["message"]


def test_no_file_sent(api):
    r = api.post("/api/import")
    assert r.status_code == 400 and r.json()["error"] == "invalid_file"


def test_missing_sheet_and_column(api):
    r = upload(api, make_workbook([["1/1", "Math", "A B", 35]], title="Wrong", extra_sheet=True))
    assert r.status_code == 400 and 'sheet "Timetable data" is missing' in r.json()["message"]
    r = upload(api, make_workbook([["1/1", "Math", 35]], header=["class", "subject", "hours_per_week"]))
    assert r.status_code == 400 and "teacher" in r.json()["message"]


def test_old_three_sheet_template_is_refused_clearly(api):
    wb = Workbook()
    wb.active.title = "Classes"
    wb.create_sheet("Teachers")
    out = io.BytesIO(); wb.save(out)
    r = upload(api, out.getvalue())
    assert r.status_code == 400 and "Timetable data" in r.json()["message"]


def test_sheet_with_no_data(api):
    r = upload(api, make_workbook([]))
    assert r.status_code == 400 and "no data" in r.json()["message"]


@pytest.mark.parametrize("hours", ["abc", -1, 36, 2.5])
def test_bad_hours_cell_names_the_row(api, hours):
    r = upload(api, make_workbook([["1/1", "Math", "A B", 5], ["1/1", "Arabic", "A B", hours]]))
    assert r.status_code == 400 and "Row 3" in r.json()["message"] and "hours_per_week" in r.json()["message"]


# ---------- confirm ----------

def test_confirm_replaces_everything_regenerates_and_generate_works(api, monkeypatch):
    monkeypatch.setenv("MADAR_AUTO_REGENERATE", "1")
    calls = []
    monkeypatch.setattr(regen.solver, "generate_timetable", lambda db: calls.append(1) or {"lessons_count": 0, "seconds": 0, "warnings": []})
    preview = upload(api, make_workbook(seed_rows())).json()
    api.post("/api/rules", json={"kind": "subject_not_in_period", "params": {"subject_id": 1, "period": 7}})
    calls.clear()
    r = api.post("/api/import/confirm", json=preview)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["generated"] is True and calls == [1]
    assert set(r.json()) >= {"generated", "violations", "warnings"}
    c = counts(api.db)
    teachers = {(row[2], row[1]) for row in seed_rows()}
    assert (c["classes"], c["teachers"], c["subjects"], c["subject_hours"], c["rules"], c["lessons"]) == (20, len(teachers), 10, 50, 0, 0)
    # existing subjects keep their Arabic names; the school works with the real solver afterwards
    assert api.db.execute("SELECT name_ar FROM subjects WHERE name = 'Math'").fetchone()[0] == "الرياضيات"


def test_confirm_the_whole_school_then_real_generate(api):
    r = api.post("/api/import/confirm", json={"rows": [dict(zip(["class", "subject", "teacher", "hours_per_week"], row)) for row in seed_rows()]})
    assert r.status_code == 200
    g = api.post("/api/timetable/generate")
    assert g.status_code == 200 and g.json()["lessons_count"] == 20 * 35 and g.json()["warnings"] == []


def test_confirm_a_small_new_school(api):
    rows = [{"class": "1/1", "subject": "Math", "teacher": "Sara K", "hours_per_week": 20},
            {"class": "1/1", "subject": "Arabic", "teacher": "Noor A", "hours_per_week": 15},
            {"class": "2/1", "subject": "Math", "teacher": "Sara K", "hours_per_week": 20},
            {"class": "2/1", "subject": "Arabic", "teacher": "Noor A", "hours_per_week": 15}]
    r = api.post("/api/import/confirm", json={"rows": rows})
    assert r.status_code == 200
    assert counts(api.db)["classes"] == 2 and counts(api.db)["teachers"] == 2 and counts(api.db)["subjects"] == 2
    teachers = {t["name"]: t for t in api.get("/api/teachers").json()}
    assert len(teachers["Sara K."]["class_ids"]) == 2
    hours = {(h["grade"], h["subject_id"]): h["per_week"] for h in api.get("/api/subject-hours").json()}
    assert hours[1, 1] == 20 and hours[1, 2] == 15 and hours[2, 1] == 0           # grades without classes get 0


def test_confirm_shortens_full_names_even_if_the_client_sends_them(api):
    rows = [{"class": "1/1", "subject": "Math", "teacher": "Sara Khaled Mutairi", "hours_per_week": 35}]
    assert api.post("/api/import/confirm", json={"rows": rows}).status_code == 200
    names = [t["name"] for t in api.get("/api/teachers").json()]
    assert names == ["Sara M."]
    assert "Khaled" not in json.dumps(api.get("/api/teachers").json())


def test_confirm_accepts_the_preview_with_warnings_sent_back(api):
    preview = upload(api, make_workbook([["1/1", "Math", "A B", 35]])).json()
    assert "warnings" in preview and api.post("/api/import/confirm", json=preview).status_code == 200


ONE = {"class": "1/1", "subject": "Math", "teacher": "A B", "hours_per_week": 35}


@pytest.mark.parametrize("change,expected", [
    ({"class": "9/9"}, "not valid"),
    ({"class": "1/6"}, "not valid"),
    ({"subject": " "}, "subject name is empty"),
    ({"hours_per_week": 40}, "0 to 35"),
    ({"hours_per_week": -1}, "0 to 35"),
])
def test_invalid_confirm_changes_nothing(api, change, expected):
    before = counts(api.db)
    r = api.post("/api/import/confirm", json={"rows": [{**ONE, **change}]})
    assert r.status_code == 422 and r.json()["error"] == "invalid_import" and expected in r.json()["message"]
    assert counts(api.db) == before


def test_confirm_rejects_duplicate_rows_and_grade_hour_conflicts(api):
    before = counts(api.db)
    r = api.post("/api/import/confirm", json={"rows": [ONE, ONE]})
    assert r.status_code == 422 and "two rows" in r.json()["message"]
    r = api.post("/api/import/confirm", json={"rows": [ONE, {**ONE, "class": "2/1", "hours_per_week": 30}]})
    assert r.status_code == 422 and "different hours" in r.json()["message"]
    r = api.post("/api/import/confirm", json={"rows": []})
    assert r.status_code == 422
    assert counts(api.db) == before


def test_confirm_with_missing_fields_is_422_and_changes_nothing(api):
    before = counts(api.db)
    r = api.post("/api/import/confirm", json={"rows": [{"class": "1/1"}]})
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"
    assert api.post("/api/import/confirm", json={"classes": []}).status_code == 422
    assert counts(api.db) == before
