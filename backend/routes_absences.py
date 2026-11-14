"""POST /api/absences: which lessons an absent teacher leaves uncovered, and who could cover each one."""
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai import llm
from ai.substitute_explainer import explain_pick, template_sentence
from errors import ApiError
from routes_school import get_db
from regen import regenerate
from substitutes import find_affected, find_long_term

router = APIRouter(prefix="/api")


class AbsenceIn(BaseModel):
    teacher_id: int
    mode: Literal["short", "long"] = "short"
    day: int | None = Field(default=None, ge=0, le=4)                    # short: one day ...
    days: list[Annotated[int, Field(ge=0, le=4)]] | None = Field(default=None, max_length=5)  # ... or several days
    lang: Literal["en", "ar"] | None = None  # the UI language; the explanation sentence is written in it (default "en")
    language: Literal["en", "ar"] | None = None  # older name for the same thing; "lang" wins if both are sent


@router.post("/absences")
def absences(body: AbsenceIn, db: sqlite3.Connection = Depends(get_db)):
    """Nothing is changed. mode "short" (default): for each day in `days` (or the single `day`) every lesson the teacher
    leaves uncovered, with ranked substitutes and a one-sentence explanation of the top pick (AI or template); the answer
    is one list ordered by day then period. mode "long": every class the teacher teaches, with ranked teachers who could
    take the subject over for good (confirm with POST /api/absences/apply)."""
    teacher = db.execute("SELECT name FROM teachers WHERE id = ?", (body.teacher_id,)).fetchone()
    if teacher is None:
        raise ApiError(404, "not_found", f"There is no teacher with id {body.teacher_id}.")
    if body.mode == "long":
        return find_long_term(db, body.teacher_id)
    days = list(dict.fromkeys(sorted(body.days))) if body.days else ([body.day] if body.day is not None else [])
    if not days:
        raise ApiError(422, "invalid_request", "day: send a day (0-4) or a list of days for a short absence.")
    if db.execute("SELECT 1 FROM lessons LIMIT 1").fetchone() is None:
        raise ApiError(409, "no_timetable", "There is no timetable yet. Generate one first.")

    result = [item for d in days for item in find_affected(db, body.teacher_id, d)]
    lang = body.lang or body.language or "en"
    ai_ok = llm.is_configured()
    for item in result:
        top = item["substitutes"][0] if item["substitutes"] else None
        if top is None:
            item["explanation"], item["explanation_source"] = None, None
        elif ai_ok:
            item["explanation"], item["explanation_source"] = explain_pick(teacher["name"], item, top, lang)
            if item["explanation_source"] == "template":
                ai_ok = False  # the AI just failed: do not wait for it again for every other lesson
        else:
            item["explanation"], item["explanation_source"] = template_sentence(item, top, lang), "template"
    return result


class AssignmentIn(BaseModel):
    class_id: int
    substitute_id: int


class ApplyIn(BaseModel):
    teacher_id: int                                   # the absent teacher
    assignments: list[AssignmentIn] = Field(min_length=1, max_length=100)


@router.post("/absences/apply")
def apply_long_absence(body: ApplyIn, db: sqlite3.Connection = Depends(get_db)):
    """Confirm a long-term absence: for each {class_id, substitute_id} the substitute becomes that class's teacher for the
    absent teacher's subject, then the timetable is regenerated. The substitute must teach the same subject and have room
    in their week (409 substitute_over_capacity otherwise). All or nothing."""
    from class_setup import capacities, weekly_loads

    absent = db.execute("SELECT id, name, subject_id FROM teachers WHERE id = ?", (body.teacher_id,)).fetchone()
    if absent is None:
        raise ApiError(404, "not_found", f"There is no teacher with id {body.teacher_id}.")
    load, cap = weekly_loads(db), capacities(db)
    subject = db.execute("SELECT name FROM subjects WHERE id = ?", (absent["subject_id"],)).fetchone()["name"]
    plan, seen = [], set()
    for a in body.assignments:
        if a.class_id in seen:
            raise ApiError(422, "invalid_request", f"Class id {a.class_id} appears twice.")
        seen.add(a.class_id)
        cls = db.execute("SELECT id, name, grade FROM classes WHERE id = ?", (a.class_id,)).fetchone()
        if cls is None or db.execute("SELECT 1 FROM teacher_classes WHERE teacher_id = ? AND class_id = ?",
                                     (absent["id"], a.class_id)).fetchone() is None:
            raise ApiError(404, "not_found", f"{absent['name']} does not teach a class with id {a.class_id}.")
        sub = db.execute("SELECT id, name, subject_id FROM teachers WHERE id = ?", (a.substitute_id,)).fetchone()
        if sub is None:
            raise ApiError(404, "not_found", f"There is no teacher with id {a.substitute_id}.")
        if sub["id"] == absent["id"] or sub["subject_id"] != absent["subject_id"]:
            raise ApiError(422, "invalid_substitute", f"{sub['name']} cannot take over {subject} in class {cls['name']}: "
                           "a substitute must be another teacher of the same subject.")
        hours = db.execute("SELECT per_week FROM subject_hours WHERE grade = ? AND subject_id = ?",
                           (cls["grade"], absent["subject_id"])).fetchone()
        n = hours["per_week"] if hours else 0
        load[sub["id"]] = load.get(sub["id"], 0) + n
        if load[sub["id"]] > cap[sub["id"]]:
            raise ApiError(409, "substitute_over_capacity", f"{sub['name']} would have {load[sub['id']]} lessons a week "
                           f"but only {cap[sub['id']]} free slots. Choose another substitute.")
        plan.append((cls, sub))
    with db:
        for cls, sub in plan:
            db.execute("DELETE FROM teacher_classes WHERE teacher_id = ? AND class_id = ?", (absent["id"], cls["id"]))
            db.execute("INSERT OR IGNORE INTO teacher_classes (teacher_id, class_id) VALUES (?, ?)", (sub["id"], cls["id"]))
    reassigned = [{"class_id": c["id"], "class": c["name"], "subject_id": absent["subject_id"], "subject": subject,
                   "from_teacher_id": absent["id"], "to_teacher_id": s["id"], "to_teacher": s["name"]} for c, s in plan]
    return {"ok": True, "reassigned": reassigned, **regenerate(db)}
