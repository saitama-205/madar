"""Excel import: template, preview (saves nothing), confirm (replaces everything), and the clear errors."""
import io
import json

import pytest
from openpyxl import Workbook, load_workbook

from database.seed import PUBLIC_DATA

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SUBJECT_HEADER = ["Subject", "Arabic name", "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5"]


def make_workbook(classes, subjects, teachers, drop_sheet=None, drop_column=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Classes"
    ws.append(["Class"])
    for c in classes:
        ws.append([c])
    ws = wb.create_sheet("Subjects and hours")
    header = [h for h in SUBJECT_HEADER if h != drop_column]
    ws.append(header)
    for row in subjects:
        ws.append([v for h, v in zip(SUBJECT_HEADER, row) if h != drop_column])
    ws = wb.create_sheet("Teachers")
    ws.append(["Teacher", "Subject", "Classes"])
    for row in teachers:
        ws.append(row)
    if drop_sheet:
        del wb[drop_sheet]
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def seed_workbook():
    """The whole real school (from the committed seed, shortened names) as an upload."""
    d = json.loads(PUBLIC_DATA.read_text(encoding="utf-8"))
    names = {s["id"]: s for s in d["subjects"]}
    hours = {}
    for h in d["subject_hours"]:
        hours.setdefault(h["subject"], {})[h["grade"]] = h["per_week"]
    subjects = [[s["name"], s["name_ar"]] + [hours[s["id"]].get(g, 0) for g in range(1, 6)] for s in d["subjects"]]
    teachers = [[t["name"], names[t["subject"]]["name"], ", ".join(t["classes"])] for t in d["teachers"]]
    return make_workbook([c["name"] for c in d["classes"]], subjects, teachers)


def upload(api, content, filename="school.xlsx"):
    return api.post("/api/import", files={"file": (filename, content, XLSX)})


def counts(db):
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("classes", "teachers", "subjects", "subject_hours", "teacher_classes", "rules", "lessons")}


# ---------- template ----------

def test_template_download(api):
    r = api.get("/api/import/template")
    assert r.status_code == 200 and r.headers["content-type"].startswith(XLSX)
    assert "madar_template.xlsx" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Classes", "Subjects and hours", "Teachers"]
    assert [c.value for c in wb["Classes"][1]] == ["Class"]
    assert [c.value for c in wb["Subjects and hours"][1]] == SUBJECT_HEADER
    assert [c.value for c in wb["Teachers"][1]] == ["Teacher", "Subject", "Classes"]
    assert wb["Classes"].max_row == 21 and wb["Subjects and hours"].max_row == 11
    assert wb["Teachers"].max_row == 1  # no personal data in the template


def test_template_can_be_uploaded_as_is(api):
    template = api.get("/api/import/template").content
    r = upload(api, template)
    assert r.status_code == 200
    body = r.json()
    assert len(body["classes"]) == 20 and body["teachers"] == [] and len(body["subject_hours"]) == 50
    assert any("has no teacher" in w for w in body["warnings"])


# ---------- preview ----------

def test_preview_of_the_whole_school_saves_nothing(api):
    before = counts(api.db)
    r = upload(api, seed_workbook())
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"classes", "teachers", "subject_hours", "warnings"}
    assert len(body["classes"]) == 20 and body["classes"][0] == {"name": "1/1", "grade": 1}
    assert len(body["teachers"]) == 79 and len(body["subject_hours"]) == 50
    assert body["subject_hours"][0] == {"grade": 1, "subject": "Islamic Education", "subject_ar": "التربية الإسلامية", "per_week": 4}
    assert body["warnings"] == []
    assert counts(api.db) == before


def test_full_names_are_shortened_in_the_preview(api):
    content = make_workbook(["1/1"], [["Math", "الرياضيات", 35, 0, 0, 0, 0]],
                            [["Sara Khaled Mutairi", "Math", "1/1"], ["Sarah Khalid Mansour", "الرياضيات", "1/1"]])
    body = upload(api, content).json()
    assert [t["name"] for t in body["teachers"]] == ["Sara M.", "Sarah M."]
    assert "Khaled" not in json.dumps(body, ensure_ascii=False) and "Mutairi" not in json.dumps(body, ensure_ascii=False)


def test_duplicate_short_names_are_told_apart(api):
    content = make_workbook(["1/1", "2/1"], [["Math", "", 35, 0, 0, 0, 0]],
                            [["Sara Khaled Mutairi", "Math", "1/1"], ["Sara Kamal Mohsen", "Math", "2/1"]])
    body = upload(api, content).json()
    assert [t["name"] for t in body["teachers"]] == ["Sara M.", "Sara M. (2)"]
    assert any("shortened" in w for w in body["warnings"])


def test_data_problems_become_warnings_not_errors(api):
    content = make_workbook(["1/1", "oops", "1/1", "9/9"], [["Math", "", 35, 0, 0, 0, 0], ["Math", "", 1, 1, 1, 1, 1]],
                            [["Huda S.", "Math", "1/1, 7/7"], ["Nora A.", "History", "1/1"], ["Lina B.", "Math", ""]])
    body = upload(api, content)
    assert body.status_code == 200
    text = " | ".join(body.json()["warnings"])
    for expected in ("oops", "appears twice", "9/9", "does not exist", "History", "Lina B. has no classes"):
        assert expected in text
    assert [t["name"] for t in body.json()["teachers"]] == ["Huda S.", "Lina B."]


def test_grade_total_warning(api):
    content = make_workbook(["1/1"], [["Math", "", 30, 0, 0, 0, 0]], [["Huda S.", "Math", "1/1"]])
    assert any("Grade 1 has 30 lessons" in w for w in upload(api, content).json()["warnings"])


# ---------- clear errors ----------

@pytest.mark.parametrize("name,content,expected", [
    ("school.csv", b"Class\n1/1\n", "Only .xlsx"),
    ("school.xlsx", b"this is not excel", "not a real .xlsx"),
    ("school.xlsx", b"", "empty"),
])
def test_wrong_files(api, name, content, expected):
    r = upload(api, content, name)
    assert r.status_code == 400 and r.json()["error"] == "invalid_file" and expected.lower() in r.json()["message"].lower()
    assert set(r.json()) == {"error", "message"}


def test_no_file_sent(api):
    r = api.post("/api/import")
    assert r.status_code == 400 and r.json()["error"] == "invalid_file"


def test_missing_sheet_and_column(api):
    ok = (["1/1"], [["Math", "", 35, 0, 0, 0, 0]], [])
    r = upload(api, make_workbook(*ok, drop_sheet="Teachers"))
    assert r.status_code == 400 and '"Teachers" is missing' in r.json()["message"]
    r = upload(api, make_workbook(*ok, drop_column="Grade 3"))
    assert r.status_code == 400 and "Grade 3" in r.json()["message"] and "missing the column" in r.json()["message"]


def test_template_with_no_data_is_empty(api):
    r = upload(api, make_workbook([], [], []))
    assert r.status_code == 400 and r.json()["error"] == "invalid_file" and "no data" in r.json()["message"]
    r = upload(api, make_workbook([], [["Math", "", 35, 0, 0, 0, 0]], []))
    assert r.status_code == 400 and "no classes" in r.json()["message"]


def test_bad_hours_cell_names_the_cell(api):
    r = upload(api, make_workbook(["1/1"], [["Math", "", "lots", 0, 0, 0, 0]], []))
    assert r.status_code == 400 and "row 2, Grade 1" in r.json()["message"]
    r = upload(api, make_workbook(["1/1"], [["Math", "", 2.5, 0, 0, 0, 0]], []))
    assert r.status_code == 400


# ---------- confirm ----------

def test_confirm_replaces_everything_and_generate_works(api):
    assert api.post("/api/timetable/generate").status_code == 200
    api.post("/api/rules", json={"kind": "subject_not_in_period", "params": {"subject_id": 8, "period": 7}})
    preview = upload(api, seed_workbook()).json()

    r = api.post("/api/import/confirm", json=preview)
    assert r.status_code == 200 and r.json()["ok"] is True
    c = counts(api.db)
    assert c["classes"] == 20 and c["teachers"] == 79 and c["subjects"] == 10 and c["subject_hours"] == 50
    assert c["rules"] == 0 and c["lessons"] == 0  # replaced, including rules and the old timetable

    g = api.post("/api/timetable/generate")
    assert g.status_code == 200, g.text
    assert g.json()["lessons_count"] == 700 and g.json()["warnings"] == []
    assert api.get("/api/analytics").json()["rule_check"]["ok"] is True


def test_confirm_a_small_new_school(api):
    content = make_workbook(
        ["1/1", "2/1"],
        [["Math", "الرياضيات", 10, 0, 0, 0, 0], ["Arabic", "العربية", 25, 0, 0, 0, 0]],
        [["Huda Salem Rashidi", "Math", "1/1, 2/1"], ["Nora Ali Ahmad", "Arabic", "1/1"], ["Mona Ali Karam", "Arabic", "2/1"]])
    preview = upload(api, content).json()
    assert api.post("/api/import/confirm", json=preview).status_code == 200
    assert [t["name"] for t in api.get("/api/teachers").json()] == ["Huda R.", "Nora A.", "Mona K."]
    assert [s["name"] for s in api.get("/api/subjects").json()] == ["Math", "Arabic"]
    g = api.post("/api/timetable/generate")
    assert g.status_code == 200, g.text
    assert g.json()["lessons_count"] == 70


def test_confirm_shortens_full_names_even_if_the_client_sends_them(api):
    body = {"classes": [{"name": "1/1", "grade": 1}],
            "subject_hours": [{"grade": 1, "subject": "Math", "subject_ar": None, "per_week": 35}],
            "teachers": [{"name": "Huda Salem Rashidi", "subject": "Math", "classes": ["1/1"]}]}
    assert api.post("/api/import/confirm", json=body).status_code == 200
    assert [t["name"] for t in api.get("/api/teachers").json()] == ["Huda R."]


GOOD = {"classes": [{"name": "1/1", "grade": 1}],
        "subject_hours": [{"grade": 1, "subject": "Math", "subject_ar": "ر", "per_week": 35}],
        "teachers": [{"name": "Huda R.", "subject": "Math", "classes": ["1/1"]}]}


@pytest.mark.parametrize("change,expected", [
    ({"classes": []}, "at least one class"),
    ({"classes": [{"name": "1/1", "grade": 2}]}, "not valid"),
    ({"classes": [{"name": "1/1", "grade": 1}, {"name": "1/1", "grade": 1}]}, "twice"),
    ({"subject_hours": []}, "at least one subject"),
    ({"subject_hours": [{"grade": 1, "subject": "Math", "per_week": 99}]}, "0 to 35"),
    ({"subject_hours": [{"grade": 6, "subject": "Math", "per_week": 5}]}, "grade must be 1 to 5"),
    ({"teachers": [{"name": "Huda R.", "subject": "History", "classes": ["1/1"]}]}, "not in the subjects"),
    ({"teachers": [{"name": "Huda R.", "subject": "Math", "classes": ["3/3"]}]}, "does not exist"),
    ({"teachers": [{"name": "Huda R.", "subject": "Math", "classes": []}, {"name": "Huda R.", "subject": "Math", "classes": []}]}, "called"),
])
def test_invalid_confirm_changes_nothing(api, change, expected):
    before = counts(api.db)
    r = api.post("/api/import/confirm", json={**GOOD, **change})
    assert r.status_code == 422 and r.json()["error"] == "invalid_import" and expected in r.json()["message"]
    assert counts(api.db) == before


def test_confirm_with_missing_fields_is_422_and_changes_nothing(api):
    before = counts(api.db)
    r = api.post("/api/import/confirm", json={"classes": []})
    assert r.status_code == 422 and set(r.json()) == {"error", "message"}
    assert counts(api.db) == before
