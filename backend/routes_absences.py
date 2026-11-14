"""POST /api/absences: which lessons an absent teacher leaves uncovered, and who could cover each one."""
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai import llm
from ai.substitute_explainer import explain_pick, template_sentence
from errors import ApiError
from routes_school import get_db
from substitutes import find_affected

router = APIRouter(prefix="/api")


class AbsenceIn(BaseModel):
    teacher_id: int
    day: int = Field(ge=0, le=4)


@router.post("/absences")
def absences(body: AbsenceIn, db: sqlite3.Connection = Depends(get_db)):
    """Nothing is changed. Each affected lesson gets ranked substitutes and a one-sentence explanation of the
    top pick (written by the AI when it is configured, otherwise by a template)."""
    teacher = db.execute("SELECT name FROM teachers WHERE id = ?", (body.teacher_id,)).fetchone()
    if teacher is None:
        raise ApiError(404, "not_found", f"There is no teacher with id {body.teacher_id}.")
    if db.execute("SELECT 1 FROM lessons LIMIT 1").fetchone() is None:
        raise ApiError(409, "no_timetable", "There is no timetable yet. Generate one first.")

    result = find_affected(db, body.teacher_id, body.day)
    ai_ok = llm.is_configured()
    for item in result:
        top = item["substitutes"][0] if item["substitutes"] else None
        if top is None:
            item["explanation"], item["explanation_source"] = None, None
        elif ai_ok:
            item["explanation"], item["explanation_source"] = explain_pick(teacher["name"], item, top)
            if item["explanation_source"] == "template":
                ai_ok = False  # the AI just failed: do not wait for it again for every other lesson
        else:
            item["explanation"], item["explanation_source"] = template_sentence(item, top), "template"
    return result
