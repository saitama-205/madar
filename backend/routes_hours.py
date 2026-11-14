"""GET /api/subject-hours and PUT /api/subject-hours/{grade}: the study plan (lessons per week of each subject)."""
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from errors import ApiError
from regen import regenerate
from routes_school import get_db
from solver import SLOTS_PER_WEEK

router = APIRouter(prefix="/api")


class HoursIn(BaseModel):
    hours: dict[str, Any]   # {"<subject_id>": lessons_per_week}


def bad(message: str) -> ApiError:
    return ApiError(400, "invalid_hours", message)


@router.get("/subject-hours")
def list_hours(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT grade, subject_id, per_week FROM subject_hours ORDER BY grade, subject_id")
    return [dict(r) for r in rows]


@router.put("/subject-hours/{grade}")
def set_hours(grade: int, body: HoursIn, db: sqlite3.Connection = Depends(get_db)):
    """Change the lessons per week of some subjects for one grade (subjects you leave out keep their hours).
    The grade's total must be exactly 35, otherwise 400 invalid_hours and nothing is changed.
    Saved, then the timetable is regenerated; the response is {grade, hours, generated, violations, warnings}."""
    if not 1 <= grade <= 5:
        raise bad("The grade must be 1 to 5.")
    subjects = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM subjects")}
    current = {r["subject_id"]: r["per_week"] for r in
               db.execute("SELECT subject_id, per_week FROM subject_hours WHERE grade = ?", (grade,))}
    new = {sid: current.get(sid, 0) for sid in subjects}
    if not body.hours:
        raise bad("Send the hours as {\"hours\": {\"<subject_id>\": number}}.")
    for key, value in body.hours.items():
        if not key.isdigit() or int(key) not in subjects:
            raise bad(f'There is no subject with id "{key}".')
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= SLOTS_PER_WEEK:
            raise bad(f"{subjects[int(key)]}: lessons per week must be a whole number from 0 to {SLOTS_PER_WEEK}.")
        new[int(key)] = value
    total = sum(new.values())
    if total != SLOTS_PER_WEEK:
        raise bad(f"Grade {grade} would have {total} lessons per week, but it must be exactly {SLOTS_PER_WEEK} "
                  "(5 days x 7 periods).")
    with db:
        db.executemany("""INSERT INTO subject_hours (grade, subject_id, per_week) VALUES (?, ?, ?)
                          ON CONFLICT (grade, subject_id) DO UPDATE SET per_week = excluded.per_week""",
                       [(grade, sid, n) for sid, n in new.items()])
    return {"grade": grade, "hours": {str(sid): n for sid, n in new.items()}, **regenerate(db)}
