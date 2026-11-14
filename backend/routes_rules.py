"""GET / POST / DELETE /api/rules. The solver keeps every saved rule the next time Generate runs."""
import json
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from errors import ApiError
from routes_school import get_db
from rule_params import parse_params

router = APIRouter(prefix="/api")


class RuleIn(BaseModel):
    kind: str
    params: dict
    source_text: str | None = Field(default=None, max_length=500)


def rule_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "kind": row["kind"], "params": json.loads(row["params"]), "source_text": row["source_text"]}


def invalid(message: str) -> ApiError:
    return ApiError(422, "invalid_rule", message)


def check_things_exist(db: sqlite3.Connection, kind: str, p) -> None:
    """The rule must point at a real subject / teacher / class (and a class must actually have that subject)."""
    def exists(table: str, id_: int, label: str):
        if db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (id_,)).fetchone() is None:
            raise invalid(f"There is no {label} with id {id_}.")

    if kind == "subject_not_in_period":
        exists("subjects", p.subject_id, "subject")
    elif kind == "teacher_unavailable":
        exists("teachers", p.teacher_id, "teacher")
    else:  # pin_lesson
        exists("classes", p.class_id, "class")
        exists("subjects", p.subject_id, "subject")
        has_subject = db.execute("""SELECT 1 FROM subject_hours h JOIN classes c ON c.grade = h.grade
                                    WHERE c.id = ? AND h.subject_id = ? AND h.per_week > 0""",
                                 (p.class_id, p.subject_id)).fetchone()
        if not has_subject:
            raise invalid("That class does not have lessons of that subject, so there is nothing to pin.")


@router.get("/rules")
def list_rules(db: sqlite3.Connection = Depends(get_db)):
    return [rule_dict(r) for r in db.execute("SELECT id, kind, params, source_text FROM rules ORDER BY id")]


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, db: sqlite3.Connection = Depends(get_db)):
    """Save a rule. It is used the next time the timetable is generated (the current one is not changed)."""
    try:
        p = parse_params(body.kind, body.params)
    except ValueError as why:
        raise invalid(f"The rule is not valid: {why}")
    check_things_exist(db, body.kind, p)

    params = p.model_dump()
    for other in db.execute("SELECT params FROM rules WHERE kind = ?", (body.kind,)):
        if json.loads(other["params"]) == params:
            raise ApiError(409, "duplicate_rule", "That rule is already saved.")

    source_text = (body.source_text or "").strip() or None
    with db:
        new_id = db.execute("INSERT INTO rules (kind, params, source_text) VALUES (?, ?, ?)",
                            (body.kind, json.dumps(params), source_text)).lastrowid
    return {"id": new_id, "kind": body.kind, "params": params, "source_text": source_text}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: sqlite3.Connection = Depends(get_db)):
    with db:
        deleted = db.execute("DELETE FROM rules WHERE id = ?", (rule_id,)).rowcount
    if not deleted:
        raise ApiError(404, "not_found", f"There is no rule with id {rule_id}.")
    return {"ok": True}
