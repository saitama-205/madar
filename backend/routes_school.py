"""Read + create endpoints for the school itself: subjects, classes, teachers, timetable."""
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from database.db import get_connection
from errors import ApiError

router = APIRouter(prefix="/api")

MAX_SECTIONS = 4  # contract: sections 1-4 in every grade


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
    """Add the next free section to a grade. It starts with no teachers, so Generate will say who is missing."""
    used = {int(r["name"].split("/")[0]) for r in db.execute("SELECT name FROM classes WHERE grade = ?", (body.grade,))}
    free = [s for s in range(1, MAX_SECTIONS + 1) if s not in used]
    if not free:
        raise ApiError(409, "grade_full", f"Grade {body.grade} already has all {MAX_SECTIONS} sections.")
    name = f"{free[0]}/{body.grade}"
    with db:
        new_id = db.execute("INSERT INTO classes (name, grade) VALUES (?, ?)", (name, body.grade)).lastrowid
    return {"id": new_id, "name": name, "grade": body.grade}


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
    return teachers_with_classes(db, "WHERE id = ?", (new_id,))[0]


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
