"""Read + create endpoints for the school itself: subjects, classes, teachers, timetable."""
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from database.db import get_connection
from analytics import compute
from class_setup import auto_assign_teachers
from errors import ApiError
from regen import regenerate
from solver import generate_timetable

router = APIRouter(prefix="/api")


def get_db():
    """One database connection per request, always closed afterwards."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


# ---------- subjects ----------

@router.get("/subjects")
def list_subjects(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT id, name, name_ar FROM subjects ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# ---------- classes ----------

class ClassIn(BaseModel):
    grade: int = Field(ge=1, le=5)


@router.get("/classes")
def list_classes(db: sqlite3.Connection = Depends(get_db)):
    # Order by grade, then section number ("2/5" = section 2 of grade 5), not alphabetically.
    rows = db.execute("""SELECT id, name, grade FROM classes
                         ORDER BY grade, CAST(substr(name, 1, instr(name, '/') - 1) AS INTEGER)""").fetchall()
    return [dict(r) for r in rows]


@router.post("/classes", status_code=201)
def create_class(body: ClassIn, db: sqlite3.Connection = Depends(get_db)):
    """Add the next free section to a grade and set it up completely:
    1. create the class (its lessons per subject come from the grade's subject_hours),
    2. assign a teacher for every subject (see class_setup.py),
    3. regenerate the timetable for the whole school.

    Steps 1 and 2 are saved before step 3 and are kept whatever happens. If generation fails, the old timetable is
    untouched and the error comes back as {error, message}."""
    used = {int(r["name"].split("/")[0]) for r in db.execute("SELECT name FROM classes WHERE grade = ?", (body.grade,))}
    section = next(s for s in range(1, len(used) + 2) if s not in used)  # smallest unused: fills gaps, else max + 1
    name = f"{section}/{body.grade}"
    with db:  # class + teacher assignments are saved together
        new_id = db.execute("INSERT INTO classes (name, grade) VALUES (?, ?)", (name, body.grade)).lastrowid
        assignments = auto_assign_teachers(db, new_id, body.grade)
    flagged = [f"{a['teacher']} for {a['subject']}" for a in assignments if a["over_capacity"]]

    try:
        result = generate_timetable(db)
    except ApiError as e:
        extra = f" Teachers over their weekly limit: {', '.join(flagged)}." if flagged and e.error != "teacher_overloaded" else ""
        raise ApiError(e.status, e.error, f"Class {name} was added and its teachers were assigned, but the timetable "
                                          f"could not be generated: {e.message}{extra} The previous timetable was kept.") from e
    except Exception as e:  # never lose the class because of an unexpected solver problem
        raise ApiError(500, "generation_failed", f"Class {name} was added and its teachers were assigned, but the "
                                                 "timetable could not be generated. The previous timetable was kept.") from e
    warnings = list(result.get("warnings", []))
    warnings += [f"No teacher exists for {a['subject']}, so it could not be assigned." for a in assignments if a["teacher_id"] is None]
    violations = compute(db)["rule_check"]["violations"]
    classes = db.execute("SELECT COUNT(DISTINCT class_id) FROM lessons").fetchone()[0]
    return {"id": new_id, "name": name, "grade": body.grade, "assignments": assignments,
            "generated": True, "violations": violations, "warnings": warnings,
            "generation": {"ok": True, "classes": classes, "lessons_count": result["lessons_count"],
                           "seconds": result["seconds"], "violations": violations, "warnings": warnings}}


# ---------- teachers ----------

class TeacherIn(BaseModel):
    name: str = Field(max_length=100)
    subject_id: int
    class_ids: list[int] = Field(default_factory=list)


def teachers_with_classes(db: sqlite3.Connection, where: str = "", args: tuple = ()):
    rows = db.execute(f"SELECT id, name, subject_id FROM teachers {where} ORDER BY id", args).fetchall()
    links = {}
    for r in db.execute("SELECT teacher_id, class_id FROM teacher_classes ORDER BY class_id"):
        links.setdefault(r["teacher_id"], []).append(r["class_id"])
    return [{**dict(r), "class_ids": links.get(r["id"], [])} for r in rows]


@router.get("/teachers")
def list_teachers(db: sqlite3.Connection = Depends(get_db)):
    return teachers_with_classes(db)


@router.post("/teachers", status_code=201)
def create_teacher(body: TeacherIn, db: sqlite3.Connection = Depends(get_db)):
    """Add a teacher. For each listed class, the new teacher TAKES OVER that subject from whoever had it
    (a class has exactly one teacher per subject). Regenerate the timetable afterwards."""
    name = body.name.strip()
    if not name:
        raise ApiError(422, "invalid_request", "name: must not be empty")
    if db.execute("SELECT 1 FROM subjects WHERE id = ?", (body.subject_id,)).fetchone() is None:
        raise ApiError(404, "subject_not_found", f"There is no subject with id {body.subject_id}.")
    class_ids = list(dict.fromkeys(body.class_ids))  # remove duplicates, keep order
    marks = ",".join("?" * len(class_ids))
    if class_ids:
        found = {r["id"] for r in db.execute(f"SELECT id FROM classes WHERE id IN ({marks})", class_ids)}
        missing = [c for c in class_ids if c not in found]
        if missing:
            raise ApiError(404, "class_not_found", f"There is no class with id {', '.join(map(str, missing))}.")

    with db:  # one transaction: either everything below happens or nothing
        if class_ids:
            db.execute(f"""DELETE FROM teacher_classes WHERE class_id IN ({marks})
                           AND teacher_id IN (SELECT id FROM teachers WHERE subject_id = ?)""",
                       [*class_ids, body.subject_id])
        new_id = db.execute("INSERT INTO teachers (name, subject_id) VALUES (?, ?)", (name, body.subject_id)).lastrowid
        db.executemany("INSERT INTO teacher_classes (teacher_id, class_id) VALUES (?, ?)",
                       [(new_id, c) for c in class_ids])
    return {**teachers_with_classes(db, "WHERE id = ?", (new_id,))[0], **regenerate(db)}


# ---------- timetable ----------

@router.get("/timetable")
def get_timetable(class_id: int | None = None, teacher_id: int | None = None,
                  db: sqlite3.Connection = Depends(get_db)):
    """Lessons of one class OR one teacher (give exactly one), ordered by day then period."""
    if (class_id is None) == (teacher_id is None):
        raise ApiError(400, "bad_request", "Give exactly one of class_id or teacher_id.")
    table, column, value = ("classes", "class_id", class_id) if class_id is not None else ("teachers", "teacher_id", teacher_id)
    if db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (value,)).fetchone() is None:
        raise ApiError(404, "not_found", f"There is no {'class' if class_id is not None else 'teacher'} with id {value}.")
    rows = db.execute(f"""
        SELECT l.class_id, c.name AS class, l.teacher_id, t.name AS teacher,
               l.subject_id, s.name AS subject, l.day, l.period
        FROM lessons l
        JOIN classes c ON c.id = l.class_id
        JOIN teachers t ON t.id = l.teacher_id
        JOIN subjects s ON s.id = l.subject_id
        WHERE l.{column} = ?
        ORDER BY l.day, l.period""", (value,)).fetchall()
    return {"lessons": [dict(r) for r in rows]}
