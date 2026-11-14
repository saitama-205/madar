"""Turn a typed request ("PE never in period 7", "المعلمة نورة لا تدرس الأحد الحصة 3") into ONE of our rule kinds.

The AI only fills in a small form (kind, subject, teacher id, class, day, period). Python then normalizes every
value, builds the params, validates them with the same code as POST /api/rules and writes the explanation itself,
so a wrong or invented answer is rejected instead of saved. Nothing is saved here: this is a preview."""
import re
import sqlite3

from ai import llm, normalize
from ai.privacy import short_name
from errors import ApiError
from rule_params import parse_params
from routes_rules import check_things_exist

HELP = ("I can turn a request into one rule at a time: a subject never in one period, a teacher unavailable in one "
        "period of one day, or a lesson fixed in a class at one day and period.")

PROMPT = """You convert ONE school scheduling request (English or Arabic) into a JSON object. Output ONLY the JSON.

Rule kinds (pick exactly one):
1) {{"kind": "subject_not_in_period", "subject": "<subject>", "period": <1-7>}}
   A subject is never taught in that period (for every class).
2) {{"kind": "teacher_unavailable", "teacher_id": <id from the teacher list>, "day": "<day>", "period": <1-7>}}
   One teacher cannot teach in that one period of that one day.
3) {{"kind": "pin_lesson", "class": "<class name>", "subject": "<subject>", "day": "<day>", "period": <1-7>}}
   That class always has that subject at that day and period.

Subjects (use the English name): {subjects}
Days: Sunday, Monday, Tuesday, Wednesday, Thursday. Periods: 1 to 7.
Classes (section/grade): {classes}
Teachers (id: name, subject): {teachers}

Never guess. If the request needs more than one rule (several days or periods, several teachers), names something
not listed above, fits none of the kinds, or a teacher is ambiguous, output exactly:
{{"error": "<one short sentence in the same language as the request saying what is unclear>"}}"""


def build_prompt(db: sqlite3.Connection) -> tuple[str, set[int]]:
    subjects = db.execute("SELECT id, name, name_ar FROM subjects ORDER BY id").fetchall()
    classes = [r["name"] for r in db.execute("SELECT name FROM classes ORDER BY grade, id")]
    teachers = db.execute("""SELECT t.id, t.name, s.name AS subject FROM teachers t
                             JOIN subjects s ON s.id = t.subject_id ORDER BY t.id""").fetchall()
    teacher_lines = [f"{t['id']}: {short_name(t['name'])}, {t['subject']}" for t in teachers]  # short names only
    prompt = PROMPT.format(
        subjects="; ".join(f"{s['name']} ({s['name_ar']})" for s in subjects),
        classes=", ".join(classes), teachers="; ".join(teacher_lines))
    return prompt, {t["id"] for t in teachers}


def _cannot(message: str) -> ApiError:
    return ApiError(422, "cannot_parse", message or HELP)


def _friendly(reason) -> str:
    text = str(reason or "").strip()
    return HELP if not text or re.search(r"json|schema|shape", text, re.IGNORECASE) else text


def to_params(db: sqlite3.Connection, raw: dict, teacher_ids: set[int]) -> tuple[str, dict]:
    """Normalize the AI's form into (kind, params). Raises cannot_parse when a value is not understood."""
    kind = raw.get("kind")
    subjects = db.execute("SELECT id, name, name_ar FROM subjects").fetchall()

    def need_period():
        p = normalize.period(raw.get("period"))
        if p is None:
            raise _cannot("The period must be a number from 1 to 7.")
        return p

    def need_day():
        d = normalize.day(raw.get("day"))
        if d is None:
            raise _cannot("The day must be one of Sunday to Thursday.")
        return d

    def need_subject():
        sid = normalize.subject_id(raw.get("subject"), subjects)
        if sid is None:
            raise _cannot("I could not find that subject in the school's subjects.")
        return sid

    if kind == "subject_not_in_period":
        return kind, {"subject_id": need_subject(), "period": need_period()}
    if kind == "teacher_unavailable":
        tid = normalize.number(raw.get("teacher_id"))
        if tid not in teacher_ids:
            raise _cannot("I could not tell which teacher you mean. Please check the name.")
        return kind, {"teacher_id": tid, "day": need_day(), "period": need_period()}
    if kind == "pin_lesson":
        name = normalize.class_name(raw.get("class"))
        row = db.execute("SELECT id FROM classes WHERE name = ?", (name,)).fetchone() if name else None
        if row is None:
            raise _cannot("I could not find that class. Classes are written like 2/5 (section/grade).")
        return kind, {"class_id": row["id"], "subject_id": need_subject(), "day": need_day(), "period": need_period()}
    raise _cannot(HELP)


def explain(db: sqlite3.Connection, kind: str, params: dict, arabic: bool) -> str:
    """The sentence shown in the preview, written by code from the validated params (so it cannot misstate them)."""
    def subject(i):
        r = db.execute("SELECT name, name_ar FROM subjects WHERE id = ?", (i,)).fetchone()
        return (r["name_ar"] or r["name"]) if arabic else r["name"]

    def day(d):
        return ("الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس")[d] if arabic else normalize.DAYS[d]

    if kind == "subject_not_in_period":
        s, p = subject(params["subject_id"]), params["period"]
        return f"{s} لن تكون أبداً في الحصة {p}." if arabic else f"{s} will never be in period {p}."
    if kind == "teacher_unavailable":
        t = db.execute("SELECT name FROM teachers WHERE id = ?", (params["teacher_id"],)).fetchone()["name"]
        d, p = day(params["day"]), params["period"]
        return f"{t} غير متاحة يوم {d} في الحصة {p}." if arabic else f"{t} will not teach on {d} in period {p}."
    c = db.execute("SELECT name FROM classes WHERE id = ?", (params["class_id"],)).fetchone()["name"]
    s, d, p = subject(params["subject_id"]), day(params["day"]), params["period"]
    return (f"الصف {c} سيكون عنده {s} يوم {d} في الحصة {p}." if arabic
            else f"Class {c} will always have {s} on {d} in period {p}.")


def parse_rule_text(db: sqlite3.Connection, text: str) -> dict:
    """Return {"kind", "params", "explanation"} (a preview, nothing saved) or raise ApiError."""
    text = (text or "").strip()
    if not text:
        raise ApiError(422, "invalid_request", "text: must not be empty")
    prompt, teacher_ids = build_prompt(db)
    try:
        raw = llm.extract_json(llm.chat([{"role": "system", "content": prompt}, {"role": "user", "content": text}],
                                        temperature=0.0, max_tokens=200))
    except llm.LLMError as e:
        raise ApiError(503, "ai_unavailable", str(e)) from e
    if "error" in raw:
        raise _cannot(_friendly(raw["error"]))

    kind, params = to_params(db, raw, teacher_ids)
    try:
        validated = parse_params(kind, params)
    except ValueError as why:
        raise ApiError(422, "invalid_rule", f"The rule is not valid: {why}") from None
    check_things_exist(db, kind, validated)
    params = validated.model_dump()
    arabic = bool(re.search("[؀-ۿ]", text))
    return {"kind": kind, "params": params, "explanation": explain(db, kind, params, arabic)}
