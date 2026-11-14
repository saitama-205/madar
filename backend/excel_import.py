"""Excel import: build the .xlsx template, turn an uploaded .xlsx into a PREVIEW, and validate + save a confirmed
import. The preview never touches the database; only `save_import` does, and only after `validate_import` passes.

One sheet, one row per class + subject:  class | subject | teacher | hours_per_week
Classes, subjects, the grade's study plan (hours per week) and the teachers with their classes are all derived from
those rows.

Teacher names are always shortened (ai.privacy.short_name: first name + initial), so full names from a spreadsheet
are never stored, shown back or sent to the AI."""
import io
import sqlite3
import zipfile
from collections import defaultdict

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field

from ai.normalize import class_name as normalize_class_name, key, subject_id as match_subject
from ai.privacy import short_name
from errors import ApiError
from solver import SLOTS_PER_WEEK

MAX_FILE_BYTES = 5 * 1024 * 1024
GRADES = range(1, 6)
SHEET = "Timetable data"
COLUMNS = ["class", "subject", "teacher", "hours_per_week"]


def invalid_file(message: str) -> ApiError:
    return ApiError(400, "invalid_file", message)


def class_order(name: str):
    section, grade = name.split("/")
    return int(grade), int(section)


# ---------------------------------------------------------------- template

def build_template(db: sqlite3.Connection) -> bytes:
    """One sheet, pre-filled with the school's current setup: a row for every class and every subject the class has
    lessons in, with its teacher's (already shortened) name and the lessons per week."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(COLUMNS)
    teacher_of = {(r["class_id"], r["subject_id"]): r["name"] for r in db.execute(
        """SELECT tc.class_id, t.subject_id, t.name FROM teacher_classes tc JOIN teachers t ON t.id = tc.teacher_id
           ORDER BY t.id DESC""")}
    classes = sorted(db.execute("SELECT id, name, grade FROM classes"), key=lambda c: class_order(c["name"]))
    subjects = db.execute("SELECT id, name FROM subjects ORDER BY id").fetchall()
    hours = {(r["grade"], r["subject_id"]): r["per_week"] for r in db.execute("SELECT * FROM subject_hours")}
    for c in classes:
        for s in subjects:
            h = hours.get((c["grade"], s["id"]), 0)
            if h > 0:
                ws.append([c["name"], s["name"], teacher_of.get((c["id"], s["id"]), ""), h])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for letter, width in zip("ABCD", (10, 22, 24, 16)):
        ws.column_dimensions[letter].width = width
    ws.column_dimensions["A"].number_format = "@"        # "1/1" would turn into a date in Excel
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- reading an upload

def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _sheet_rows(wb) -> list[dict]:
    """The data rows of the sheet as dicts keyed by the template's column names. Blank rows are dropped.
    Each dict also has "_row" (the Excel row number) for error messages."""
    match = next((n for n in wb.sheetnames if key(n) == key(SHEET)), None)
    if match is None:
        if len(wb.sheetnames) == 1:
            match = wb.sheetnames[0]       # a single sheet with another name is fine
        else:
            raise invalid_file(f'The sheet "{SHEET}" is missing. Download the template and keep its sheet and header row.')
    rows = list(wb[match].iter_rows(values_only=True))
    header = [key(_cell(c)) for c in (rows[0] if rows else [])]
    positions, missing = {}, []
    for col in COLUMNS:
        if key(col) in header:
            positions[col] = header.index(key(col))
        else:
            missing.append(col)
    if missing:
        raise invalid_file(f'The sheet "{match}" is missing the column(s): {", ".join(missing)}. '
                           "Keep the header row from the template.")
    out = []
    for number, row in enumerate(rows[1:], start=2):
        record = {col: (row[i] if i < len(row) else None) for col, i in positions.items()}
        if any(_cell(v) for v in record.values()):
            out.append({**record, "_row": number})
    return out


def read_workbook(content: bytes, filename: str):
    if not content:
        raise invalid_file("The file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise invalid_file("The file is too large (the limit is 5 MB).")
    if not (filename or "").lower().endswith(".xlsx"):
        raise invalid_file("Only .xlsx files can be imported (Excel Workbook). Please use the template.")
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise invalid_file("This is not a real .xlsx file. Save it from Excel as \"Excel Workbook (.xlsx)\".")
    try:
        return load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, KeyError, ValueError, OSError, zipfile.BadZipFile):
        raise invalid_file("This file could not be read as an Excel workbook.") from None


def parse_upload(content: bytes, filename: str, db: sqlite3.Connection | None = None) -> dict:
    """Return the preview {rows: [{class, subject, teacher, hours_per_week}], warnings}. Nothing is saved.
    With `db`, a subject written in Arabic (or any known alias) is turned into the school's English subject name."""
    wb = read_workbook(content, filename)
    try:
        raw_rows = _sheet_rows(wb)
    finally:
        wb.close()
    if not raw_rows:
        raise invalid_file("The file has no data. Fill in the template: one row per class and subject.")

    known = db.execute("SELECT id, name, name_ar FROM subjects").fetchall() if db is not None else []
    warnings: list[str] = []
    rows, seen = [], set()
    short_of: dict[tuple, str] = {}          # (subject key, raw teacher name) -> shortened name
    owner: dict[tuple, str] = {}             # (subject key, shortened name) -> raw teacher name that owns it
    for r in raw_rows:
        where = f"Row {r['_row']}"
        cname = normalize_class_name(_cell(r["class"]))
        if cname is None or int(cname.split("/")[1]) not in GRADES or int(cname.split("/")[0]) < 1:
            warnings.append(f'{where}: "{_cell(r["class"])}" is not a class like 2/5 (section/grade, grade 1 to 5), '
                            "so the row was ignored.")
            continue
        subject = _cell(r["subject"])
        if not subject:
            warnings.append(f"{where}: the subject is empty, so the row was ignored.")
            continue
        sid = match_subject(subject, known) if known else None
        if sid is not None:
            subject = next(s["name"] for s in known if s["id"] == sid)
        text = _cell(r["hours_per_week"])
        raw = r["hours_per_week"]
        try:
            hours = int(text)
            if hours < 0 or hours > SLOTS_PER_WEEK or (isinstance(raw, float) and not raw.is_integer()):
                raise ValueError
        except ValueError:
            raise invalid_file(f'{where}: hours_per_week "{text}" must be a whole number of lessons per week '
                               f"(0 to {SLOTS_PER_WEEK}).") from None
        if (cname, key(subject)) in seen:
            warnings.append(f"{where}: class {cname} already has a row for {subject}; the duplicate was ignored.")
            continue
        seen.add((cname, key(subject)))

        raw_teacher = _cell(r["teacher"])
        teacher = ""
        if raw_teacher:
            tk = (key(subject), key(raw_teacher))
            if tk not in short_of:
                short = short_name(raw_teacher)             # never keep a full name
                if (key(subject), short) in owner and owner[(key(subject), short)] != tk[1]:
                    count = sum(1 for (s, _), v in short_of.items() if s == key(subject) and v.split(" (")[0] == short) + 1
                    warnings.append(f'Two {subject} teachers are shortened to "{short}"; the second is saved as '
                                    f'"{short} ({count})".')
                    short = f"{short} ({count})"
                else:
                    owner[(key(subject), short)] = tk[1]
                short_of[tk] = short
            teacher = short_of[tk]
        rows.append({"class": cname, "subject": subject, "teacher": teacher, "hours_per_week": hours})
    if not rows:
        raise invalid_file("The file has no valid rows (a class like 2/5, a subject and the hours per week).")

    warnings += _consistency_warnings(rows)
    return {"rows": rows, "warnings": warnings}


def _consistency_warnings(rows: list[dict]) -> list[str]:
    out = []
    per_class = defaultdict(int)
    for r in rows:
        per_class[r["class"]] += r["hours_per_week"]
    for c in sorted(per_class, key=class_order):
        if per_class[c] != SLOTS_PER_WEEK:
            out.append(f"Class {c} has {per_class[c]} lessons per week in total, but every class needs exactly "
                       f"{SLOTS_PER_WEEK}. Generate will refuse until this is fixed.")
    by_grade = defaultdict(lambda: defaultdict(set))       # grade -> subject key -> {hours}
    for r in rows:
        by_grade[int(r["class"].split("/")[1])][key(r["subject"])].add(r["hours_per_week"])
    for g in sorted(by_grade):
        for sk, hs in by_grade[g].items():
            if len(hs) > 1:
                name = next(r["subject"] for r in rows if key(r["subject"]) == sk)
                out.append(f"Grade {g}: classes disagree on the hours of {name} ({', '.join(map(str, sorted(hs)))}). "
                           "All classes of a grade must have the same hours, so Confirm will refuse.")
    for r in rows:
        if r["hours_per_week"] > 0 and not r["teacher"]:
            out.append(f"Class {r['class']} has no teacher for {r['subject']}, so Generate will skip it.")
    return out


# ---------------------------------------------------------------- confirm

class RowIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    class_: str = Field(alias="class", max_length=20)
    subject: str = Field(max_length=100)
    teacher: str | None = Field(default="", max_length=100)
    hours_per_week: int


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="ignore")  # "warnings" from the preview may be sent back and is not needed
    rows: list[RowIn] = Field(max_length=5000)


def _bad(message: str) -> ApiError:
    return ApiError(422, "invalid_import", message)


def validate_import(data: ConfirmIn) -> dict:
    """Check everything again (the preview may have been edited). Returns the cleaned data or raises 422."""
    if not data.rows:
        raise _bad("There must be at least one row.")
    classes: dict[str, int] = {}
    subjects: dict[str, None] = {}
    hours_by: dict[tuple, int] = {}          # (grade, subject) -> per_week
    taught: dict[tuple, list] = defaultdict(list)    # (shortened name, subject) -> [class names]
    seen = set()
    for r in data.rows:
        name = normalize_class_name(r.class_)
        if name is None or int(name.split("/")[0]) < 1 or int(name.split("/")[1]) not in GRADES:
            raise _bad(f'Class "{r.class_}" is not valid. Use section/grade like 2/5, grade 1 to 5.')
        grade = int(name.split("/")[1])
        subject = r.subject.strip()
        if not subject:
            raise _bad(f"Class {name}: a subject name is empty.")
        known = next((n for n in subjects if key(n) == key(subject)), None)
        subject = known or subject
        subjects.setdefault(subject, None)
        if not 0 <= r.hours_per_week <= SLOTS_PER_WEEK:
            raise _bad(f"Class {name}, {subject}: hours_per_week must be 0 to {SLOTS_PER_WEEK}.")
        if (name, subject) in seen:
            raise _bad(f"Class {name} has two rows for {subject}.")
        seen.add((name, subject))
        classes[name] = grade
        if (grade, subject) in hours_by and hours_by[grade, subject] != r.hours_per_week:
            raise _bad(f"Grade {grade}: {subject} has different hours in different classes "
                       f"({hours_by[grade, subject]} and {r.hours_per_week}). All classes of a grade need the same hours.")
        hours_by[grade, subject] = r.hours_per_week
        teacher = short_name(r.teacher or "") if (r.teacher or "").strip() else ""
        if teacher and r.hours_per_week > 0:
            taught[teacher, subject].append(name)
    return {"classes": [{"name": n, "grade": g} for n, g in sorted(classes.items(), key=lambda kv: class_order(kv[0]))],
            "subjects": subjects,
            "hours": [{"grade": g, "subject": s, "per_week": hours_by.get((g, s), 0)} for s in subjects for g in GRADES],
            "teachers": [{"name": t, "subject": s, "classes": cs} for (t, s), cs in taught.items()]}


TABLES = ["lessons", "rules", "teacher_classes", "teachers", "subject_hours", "classes", "subjects"]


def save_import(db: sqlite3.Connection, clean: dict) -> None:
    """Replace ALL data (including lessons and rules) with the import, in one transaction.
    A subject that already exists keeps its Arabic name."""
    arabic = {key(r["name"]): r["name_ar"] for r in db.execute("SELECT name, name_ar FROM subjects")}
    with db:
        for table in TABLES:
            db.execute(f"DELETE FROM {table}")
        subject_ids = {}
        for i, name in enumerate(clean["subjects"], start=1):
            db.execute("INSERT INTO subjects (id, name, name_ar) VALUES (?, ?, ?)", (i, name, arabic.get(key(name))))
            subject_ids[name] = i
        db.executemany("INSERT INTO subject_hours (grade, subject_id, per_week) VALUES (?, ?, ?)",
                       [(h["grade"], subject_ids[h["subject"]], h["per_week"]) for h in clean["hours"]])
        class_ids = {c["name"]: db.execute("INSERT INTO classes (name, grade) VALUES (?, ?)",
                                           (c["name"], c["grade"])).lastrowid for c in clean["classes"]}
        for t in clean["teachers"]:
            tid = db.execute("INSERT INTO teachers (name, subject_id) VALUES (?, ?)",
                             (t["name"], subject_ids[t["subject"]])).lastrowid
            db.executemany("INSERT INTO teacher_classes (teacher_id, class_id) VALUES (?, ?)",
                           [(tid, class_ids[c]) for c in t["classes"]])
