"""Excel import: build the .xlsx template, turn an uploaded .xlsx into a PREVIEW, and validate + save a confirmed
import. The preview never touches the database; only `save_import` does, and only after `validate_import` passes.

Teacher names are always shortened (ai.privacy.short_name: first name + initial), so full names from a spreadsheet
are never stored, shown back or sent to the AI."""
import io
import re
import sqlite3
import zipfile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field

from ai.normalize import class_name as normalize_class_name, key
from ai.privacy import short_name
from errors import ApiError
from solver import SLOTS_PER_WEEK

MAX_FILE_BYTES = 5 * 1024 * 1024
GRADES = range(1, 6)
SHEET_CLASSES, SHEET_SUBJECTS, SHEET_TEACHERS = "Classes", "Subjects and hours", "Teachers"
CLASS_COLUMNS = ["Class"]
SUBJECT_COLUMNS = ["Subject", "Arabic name"] + [f"Grade {g}" for g in GRADES]
TEACHER_COLUMNS = ["Teacher", "Subject", "Classes"]


def invalid_file(message: str) -> ApiError:
    return ApiError(400, "invalid_file", message)


# ---------------------------------------------------------------- template

def build_template(db: sqlite3.Connection) -> bytes:
    """A workbook with the three sheets. Classes and subjects/hours are pre-filled with the school's current setup
    (no personal data); the Teachers sheet only has its header (it would hold personal names)."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_CLASSES
    ws.append(CLASS_COLUMNS)
    for r in db.execute("""SELECT name FROM classes
                           ORDER BY grade, CAST(substr(name, 1, instr(name, '/') - 1) AS INTEGER)"""):
        ws.append([r["name"]])

    ws = wb.create_sheet(SHEET_SUBJECTS)
    ws.append(SUBJECT_COLUMNS)
    hours = {(r["grade"], r["subject_id"]): r["per_week"] for r in db.execute("SELECT * FROM subject_hours")}
    for s in db.execute("SELECT id, name, name_ar FROM subjects ORDER BY id"):
        ws.append([s["name"], s["name_ar"]] + [hours.get((g, s["id"]), 0) for g in GRADES])

    ws = wb.create_sheet(SHEET_TEACHERS)
    ws.append(TEACHER_COLUMNS)

    for sheet, widths in ((wb[SHEET_CLASSES], [12]), (wb[SHEET_SUBJECTS], [22, 24, 10, 10, 10, 10, 10]),
                          (wb[SHEET_TEACHERS], [24, 22, 40])):
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for i, w in enumerate(widths):
            sheet.column_dimensions[chr(ord("A") + i)].width = w
    # "1/1" would turn into a date in Excel: keep the class columns as text
    wb[SHEET_CLASSES].column_dimensions["A"].number_format = "@"
    wb[SHEET_TEACHERS].column_dimensions["C"].number_format = "@"
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


def _sheet_rows(wb, title: str, columns: list[str], optional: tuple[str, ...] = ()) -> list[dict]:
    """The data rows of one sheet as dicts keyed by the template's column names. Blank rows are dropped.
    Each dict also has "_row" (the Excel row number) for error messages."""
    match = next((n for n in wb.sheetnames if key(n) == key(title)), None)
    if match is None:
        raise invalid_file(f'The sheet "{title}" is missing. Download the template and keep its three sheets.')
    rows = list(wb[match].iter_rows(values_only=True))
    header = [key(_cell(c)) for c in (rows[0] if rows else [])]
    positions, missing = {}, []
    for col in columns:
        if key(col) in header:
            positions[col] = header.index(key(col))
        elif col not in optional:
            missing.append(col)
    if missing:
        raise invalid_file(f'The sheet "{title}" is missing the column(s): {", ".join(missing)}. '
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


def parse_upload(content: bytes, filename: str) -> dict:
    """Return the preview {classes, teachers, subject_hours, warnings}. Nothing is saved."""
    wb = read_workbook(content, filename)
    try:
        class_rows = _sheet_rows(wb, SHEET_CLASSES, CLASS_COLUMNS)
        subject_rows = _sheet_rows(wb, SHEET_SUBJECTS, SUBJECT_COLUMNS, optional=("Arabic name",))
        teacher_rows = _sheet_rows(wb, SHEET_TEACHERS, TEACHER_COLUMNS)
    finally:
        wb.close()
    if not class_rows and not subject_rows and not teacher_rows:
        raise invalid_file("The file has no data. Fill in the template (classes, subjects and hours, teachers).")
    if not class_rows:
        raise invalid_file(f'The sheet "{SHEET_CLASSES}" has no classes.')
    if not subject_rows:
        raise invalid_file(f'The sheet "{SHEET_SUBJECTS}" has no subjects.')

    warnings: list[str] = []

    # classes
    classes, seen = [], set()
    for r in class_rows:
        name = normalize_class_name(_cell(r["Class"]))
        if name is None or int(name.split("/")[1]) not in GRADES or int(name.split("/")[0]) < 1:
            warnings.append(f'Classes row {r["_row"]}: "{_cell(r["Class"])}" is not a class like 2/5 '
                            "(section/grade, grade 1 to 5), so it was ignored.")
        elif name in seen:
            warnings.append(f'Classes row {r["_row"]}: class {name} appears twice; the duplicate was ignored.')
        else:
            seen.add(name)
            classes.append({"name": name, "grade": int(name.split("/")[1])})
    if not classes:
        raise invalid_file(f'The sheet "{SHEET_CLASSES}" has no valid class names (they look like 2/5).')

    # subjects and hours
    subject_hours, subjects, seen_subjects = [], [], set()
    for r in subject_rows:
        name = _cell(r["Subject"])
        if not name:
            warnings.append(f'Subjects row {r["_row"]}: the subject name is empty, so the row was ignored.')
            continue
        if key(name) in seen_subjects:
            warnings.append(f'Subjects row {r["_row"]}: subject "{name}" appears twice; the duplicate was ignored.')
            continue
        seen_subjects.add(key(name))
        ar = _cell(r.get("Arabic name"))
        subjects.append({"name": name, "name_ar": ar})
        for g in GRADES:
            raw = r[f"Grade {g}"]
            text = _cell(raw)
            try:
                hours = 0 if text == "" else int(text)
                if hours < 0 or hours > SLOTS_PER_WEEK or (isinstance(raw, float) and not raw.is_integer()):
                    raise ValueError
            except ValueError:
                raise invalid_file(f'Subjects row {r["_row"]}, Grade {g}: "{text}" must be a whole number of lessons '
                                   f"per week (0 to {SLOTS_PER_WEEK}).") from None
            subject_hours.append({"grade": g, "subject": name, "subject_ar": ar, "per_week": hours})
    if not subjects:
        raise invalid_file(f'The sheet "{SHEET_SUBJECTS}" has no subjects.')

    grades_used = sorted({c["grade"] for c in classes})
    for g in grades_used:
        total = sum(h["per_week"] for h in subject_hours if h["grade"] == g)
        if total != SLOTS_PER_WEEK:
            warnings.append(f"Grade {g} has {total} lessons per week in total, but every class needs exactly "
                            f"{SLOTS_PER_WEEK}. Generate will refuse until this is fixed.")

    # teachers
    subject_by_key = {}
    for s in subjects:
        subject_by_key[key(s["name"])] = s["name"]
        if s["name_ar"]:
            subject_by_key[key(s["name_ar"])] = s["name"]
    class_names = {c["name"] for c in classes}
    teachers, used_names = [], {}
    for r in teacher_rows:
        raw_name = _cell(r["Teacher"])
        if not raw_name:
            warnings.append(f'Teachers row {r["_row"]}: the teacher name is empty, so the row was ignored.')
            continue
        subject = subject_by_key.get(key(_cell(r["Subject"])))
        short = short_name(raw_name)  # never keep a full name
        if subject is None:
            warnings.append(f'Teachers row {r["_row"]}: {short} has subject "{_cell(r["Subject"])}", which is not in the '
                            "subjects sheet, so the teacher was ignored.")
            continue
        listed = [normalize_class_name(p) or p.strip() for p in re.split(r"[,،;\n]+", _cell(r["Classes"])) if p.strip()]
        known = list(dict.fromkeys(c for c in listed if c in class_names))
        for c in dict.fromkeys(listed):
            if c not in class_names:
                warnings.append(f'Teachers row {r["_row"]}: {short} is listed for class "{c}", which does not exist, so it was ignored.')
        if not known:
            warnings.append(f"Teacher {short} has no classes.")
        count = used_names.get(short, 0) + 1
        used_names[short] = count
        if count > 1:
            warnings.append(f'Two teachers are shortened to "{short}"; the second is saved as "{short} ({count})".')
            short = f"{short} ({count})"
        teachers.append({"name": short, "subject": subject, "classes": known})

    # who is missing / double booked
    taught = {}
    for t in teachers:
        for c in t["classes"]:
            taught.setdefault((c, t["subject"]), []).append(t["name"])
    for (c, s), names in sorted(taught.items()):
        if len(names) > 1:
            warnings.append(f"Class {c} has more than one {s} teacher ({', '.join(names)}). A class needs exactly one.")
    for c in classes:
        missing = [h["subject"] for h in subject_hours
                   if h["grade"] == c["grade"] and h["per_week"] > 0 and (c["name"], h["subject"]) not in taught]
        if missing:
            warnings.append(f'Class {c["name"]} has no teacher for {", ".join(missing[:5])}'
                            f'{" and more" if len(missing) > 5 else ""}, so Generate will skip it.')
    return {"classes": classes, "teachers": teachers, "subject_hours": subject_hours, "warnings": warnings}


# ---------------------------------------------------------------- confirm

class ClassIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(max_length=20)
    grade: int


class TeacherIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(max_length=100)
    subject: str = Field(max_length=100)
    classes: list[str] = Field(default_factory=list, max_length=200)


class HoursIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    grade: int
    subject: str = Field(max_length=100)
    subject_ar: str | None = Field(default=None, max_length=100)
    per_week: int


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="ignore")  # "warnings" from the preview may be sent back and is not needed
    classes: list[ClassIn] = Field(max_length=500)
    teachers: list[TeacherIn] = Field(max_length=1000)
    subject_hours: list[HoursIn] = Field(max_length=500)


def _bad(message: str) -> ApiError:
    return ApiError(422, "invalid_import", message)


def validate_import(data: ConfirmIn) -> dict:
    """Check everything again (the preview may have been edited). Returns the cleaned data or raises 422."""
    if not data.classes:
        raise _bad("There must be at least one class.")
    if not data.subject_hours:
        raise _bad("There must be at least one subject with hours.")
    classes, names = [], set()
    for c in data.classes:
        name = normalize_class_name(c.name)
        if name is None or int(name.split("/")[0]) < 1 or int(name.split("/")[1]) != c.grade or c.grade not in GRADES:
            raise _bad(f'Class "{c.name}" (grade {c.grade}) is not valid. Use section/grade like 2/5, grade 1 to 5, '
                       "and the grade must match the name.")
        if name in names:
            raise _bad(f"Class {name} appears twice.")
        names.add(name)
        classes.append({"name": name, "grade": c.grade})

    subjects: dict[str, str | None] = {}
    hours, seen = [], set()
    for h in data.subject_hours:
        name = h.subject.strip()
        if not name:
            raise _bad("A subject name is empty.")
        if h.grade not in GRADES:
            raise _bad(f"Subject {name}: grade must be 1 to 5.")
        if not 0 <= h.per_week <= SLOTS_PER_WEEK:
            raise _bad(f"Subject {name}, grade {h.grade}: lessons per week must be 0 to {SLOTS_PER_WEEK}.")
        if (key(name), h.grade) in seen:
            raise _bad(f"Subject {name} has two rows for grade {h.grade}.")
        seen.add((key(name), h.grade))
        known = next((n for n in subjects if key(n) == key(name)), None)
        subjects.setdefault(known or name, (h.subject_ar or "").strip() or None)
        hours.append({"grade": h.grade, "subject": known or name, "per_week": h.per_week})

    teachers, used = [], set()
    for t in data.teachers:
        short = short_name(t.name)
        if not short:
            raise _bad("A teacher name is empty.")
        if short in used:
            raise _bad(f'Two teachers are called "{short}". Make the names different (for example add "(2)").')
        used.add(short)
        subject = next((n for n in subjects if key(n) == key(t.subject)), None)
        if subject is None:
            raise _bad(f'Teacher {short}: subject "{t.subject}" is not in the subjects list.')
        listed = []
        for c in t.classes:
            cn = normalize_class_name(c) or c
            if cn not in names:
                raise _bad(f'Teacher {short}: class "{c}" does not exist.')
            listed.append(cn)
        teachers.append({"name": short, "subject": subject, "classes": list(dict.fromkeys(listed))})
    return {"classes": classes, "subjects": subjects, "hours": hours, "teachers": teachers}


TABLES = ["lessons", "rules", "teacher_classes", "teachers", "subject_hours", "classes", "subjects"]


def save_import(db: sqlite3.Connection, clean: dict) -> None:
    """Replace ALL data (including lessons and rules) with the import, in one transaction."""
    with db:
        for table in TABLES:
            db.execute(f"DELETE FROM {table}")
        subject_ids = {}
        for i, (name, name_ar) in enumerate(clean["subjects"].items(), start=1):
            db.execute("INSERT INTO subjects (id, name, name_ar) VALUES (?, ?, ?)", (i, name, name_ar))
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
