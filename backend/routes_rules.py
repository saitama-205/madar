"""GET / POST / DELETE /api/rules. The solver keeps every saved rule the next time Generate runs."""
import json
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from errors import ApiError
from routes_school import get_db
from regen import regenerate
from rule_params import parse_params

router = APIRouter(prefix="/api")


class RuleIn(BaseModel):
    """One rule ({kind, params}) or several saved together ({rules: [{kind, params}, ..]}, e.g. the two pins of a swap)."""
    kind: str | None = None
    params: dict | None = None
    rules: list[dict] | None = Field(default=None, max_length=10)
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


class ParseIn(BaseModel):
    text: str = Field(max_length=500)


@router.post("/rules/parse")
def parse_rule(body: ParseIn, db: sqlite3.Connection = Depends(get_db)):
    """Preview only: turn typed English/Arabic into a rule. Nothing is saved; the user confirms with POST /api/rules."""
    from ai.rule_parser import parse_rule_text  # imported here because rule_parser itself imports this module
    return parse_rule_text(db, body.text)


@router.get("/rules")
def list_rules(db: sqlite3.Connection = Depends(get_db)):
    return [rule_dict(r) for r in db.execute("SELECT id, kind, params, source_text FROM rules ORDER BY id")]


def _validated(db: sqlite3.Connection, kind, params) -> dict:
    try:
        p = parse_params(kind or "", params)
    except ValueError as why:
        raise invalid(f"The rule is not valid: {why}")
    check_things_exist(db, kind, p)
    return p.model_dump()


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, db: sqlite3.Connection = Depends(get_db)):
    """Save a rule, then regenerate the timetable (see regen.py). The response is the saved rule plus
    {generated, violations, warnings}. Send {"rules": [..]} to save several in one go (all or none)."""
    source_text = (body.source_text or "").strip() or None
    if body.rules is not None:
        if not body.rules:
            raise invalid("rules must not be empty.")
        items = [(r.get("kind"), r.get("params")) for r in body.rules]
    elif body.kind is not None:
        items = [(body.kind, body.params)]
    else:
        raise invalid("Send either kind and params, or a list of rules.")

    checked = [(kind, _validated(db, kind, params)) for kind, params in items]
    if body.rules is None:
        for other in db.execute("SELECT params FROM rules WHERE kind = ?", (checked[0][0],)):
            if json.loads(other["params"]) == checked[0][1]:
                raise ApiError(409, "duplicate_rule", "That rule is already saved.")

    saved = []
    with db:
        for kind, params in checked:
            exists = any(json.loads(o["params"]) == params for o in db.execute("SELECT params FROM rules WHERE kind = ?", (kind,)))
            if exists:      # saving a swap twice (or half of it) must not fail on the part that is already there
                continue
            new_id = db.execute("INSERT INTO rules (kind, params, source_text) VALUES (?, ?, ?)",
                                (kind, json.dumps(params), source_text)).lastrowid
            saved.append({"id": new_id, "kind": kind, "params": params, "source_text": source_text})
    outcome = regenerate(db)
    if body.rules is None:
        return {**saved[0], **outcome}
    return {"rules": saved, **outcome}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: sqlite3.Connection = Depends(get_db)):
    with db:
        deleted = db.execute("DELETE FROM rules WHERE id = ?", (rule_id,)).rowcount
    if not deleted:
        raise ApiError(404, "not_found", f"There is no rule with id {rule_id}.")
    return {"ok": True}
