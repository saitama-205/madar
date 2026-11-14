"""Madar assistant: an AI agent that works through a request step by step, but never changes any data.

How it works (one POST /api/agent request):
  1. The model gets the request plus a list of TOOLS it may call (OpenRouter "tool calling").
  2. It calls tools to look things up (teachers, timetables, rules, who could cover) and to PROPOSE changes.
  3. Python runs each tool against the database and sends back the result; the model decides the next step.
  4. When it stops calling tools, its last message is the reply. At most MAX_STEPS rounds.

Safety, matching CONTRACT.md ("the AI only translates/explains; the user always sees a preview"):
  - No tool writes to the database. A "proposal" is a ready-made request body for an EXISTING endpoint
    (POST /api/rules or POST /api/teachers); the user approves it in the app, which then calls that endpoint.
  - Every proposal is validated by the same code as those endpoints (rule_params + check_things_exist), and its
    description and impact (lessons that move, teacher load) are computed by Python, not written by the AI.
  - Only shortened teacher names are ever sent to the AI (ai.privacy.short_name).
"""
import json
import re
import sqlite3

from ai import llm, normalize
from ai.privacy import short_name
from ai.rule_parser import explain
from errors import ApiError
from names_en import english_name
from routes_rules import check_things_exist
from rule_params import parse_params
from substitutes import find_affected

MAX_STEPS = 8            # tool rounds per request; the last round must answer in words
MAX_TOOL_RESULT = 6000   # characters of one tool result sent back to the model
SLOTS_PER_WEEK = 35
DAYS = normalize.DAYS    # ["Sunday", ..., "Thursday"], index = day number


def _iso(text: str) -> str:
    """Wrap a name so an Arabic name inside an English sentence (or the reverse) keeps its own direction."""
    return f"\u2068{text}\u2069"

SYSTEM = """You are Madar's scheduling assistant for an elementary school in Kuwait (5 days Sunday-Thursday,
7 periods a day, 35 lessons per class per week). A constraint solver builds the timetable; you never build it.

What you do: understand the admin's request, look up what you need with the tools, then PROPOSE changes with
propose_rule or propose_new_teacher. You cannot save anything: the admin approves or rejects each proposal in the app,
then presses Generate. Never say a change is saved or done.

Rules:
- Teachers have Arabic names and English spellings (name_en, e.g. Fatima J.); the admin may use either. Match on both.
  In an English answer call teachers by name_en, in an Arabic answer by their Arabic name.
- Use ids only from tool results or the lists below. Never invent a teacher, class, subject, day or period.
- If a teacher name matches several people, or something important is missing (for example who replaces a teacher
  who left), ask ONE short question instead of guessing.
- Read every proposal result. If ok is false, fix the problem or explain it; if the impact warns that the timetable
  becomes impossible, say so and suggest another way.
- A teacher who leaves: get their classes (get_timetable with teacher_id), then propose_new_teacher for the
  replacement with those class ids (the new teacher takes over that subject in those classes).
- A teacher away for a single day: use find_cover. That is advice only, no proposal is needed.
- An absence given only as a time (a day and a period, maybe a class, no teacher name): if a class is named, use
  get_slot with that class to see the lesson and its teacher, then who_is_free with that day, period and subject.
  With no class, use who_is_free for that day and period, and ask which class if it matters. Advice only.
- Answer in {language}, in at most 5 short sentences or bullets. Mention proposals by their number (P1, P2...).

Subjects (id: English / Arabic): {subjects}
Classes (id: name, "section/grade"): {classes}
Days: 0 Sunday, 1 Monday, 2 Tuesday, 3 Wednesday, 4 Thursday. Periods 1 to 7."""


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


_INT = {"type": "integer"}
_DAY = {"type": "integer", "minimum": 0, "maximum": 4, "description": "0 Sunday .. 4 Thursday"}
_PERIOD = {"type": "integer", "minimum": 1, "maximum": 7}

TOOLS = [
    _fn("find_teachers", "Find teachers by part of their name (English or Arabic) and/or subject. "
        "Leave both empty to list everyone. Returns id, name, subject and classes.",
        {"name": {"type": "string"}, "subject": {"type": "string", "description": "English or Arabic subject name"}}, []),
    _fn("get_timetable", "The saved week of ONE class or ONE teacher (give class_id or teacher_id). For a teacher it also "
        "returns lessons per day and the slots they are marked unavailable.",
        {"class_id": _INT, "teacher_id": _INT}, []),
    _fn("list_rules", "Saved rules, optionally only those about one teacher.", {"teacher_id": _INT}, []),
    _fn("find_cover", "For a teacher absent on one day: each lesson they would miss and up to 3 free teachers who could "
        "cover it (same subject first, then the lightest day). Advice only, nothing is changed.",
        {"teacher_id": _INT, "day": _DAY}, ["teacher_id", "day"]),
    _fn("get_slot", "Lessons in ONE slot (day + period) across the school, or only for one class: class, subject and teacher.",
        {"day": _DAY, "period": _PERIOD, "class_id": _INT}, ["day", "period"]),
    _fn("who_is_free", "Teachers free in one slot (no lesson there and not marked unavailable), with their lessons that day. "
        "Give subject_id to list teachers of that subject first. Advice only, nothing is changed.",
        {"day": _DAY, "period": _PERIOD, "subject_id": _INT}, ["day", "period"]),
    _fn("propose_rule", "Propose ONE rule for the admin to approve. kind=subject_not_in_period needs subject_id, period. "
        "kind=teacher_unavailable needs teacher_id, day, period (one slot; call again for each slot). "
        "kind=pin_lesson needs class_id, subject_id, day, period.",
        {"kind": {"type": "string", "enum": ["subject_not_in_period", "teacher_unavailable", "pin_lesson"]},
         "subject_id": _INT, "teacher_id": _INT, "class_id": _INT, "day": _DAY, "period": _PERIOD,
         "reason": {"type": "string", "description": "Short note saved with the rule"}}, ["kind"]),
    _fn("propose_new_teacher", "Propose adding a teacher who takes over one subject in the given classes "
        "(each class has one teacher per subject, so the current teacher of that subject loses those classes).",
        {"name": {"type": "string"}, "subject_id": _INT, "class_ids": {"type": "array", "items": _INT},
         "reason": {"type": "string"}}, ["name", "subject_id", "class_ids"]),
]


# ---------------------------------------------------------------- the OpenRouter call

def _call_model(messages: list[dict], allow_tools: bool) -> dict:
    """One chat completion with tools. Returns the assistant message dict. Raises llm.LLMError."""
    key = llm.get_api_key()
    if key is None:
        raise llm.LLMUnavailable("The AI is not configured (OPENROUTER_API_KEY is missing).")
    payload = {"model": llm.get_model(), "messages": messages, "tools": TOOLS,
               "tool_choice": "auto" if allow_tools else "none", "temperature": 0.1, "max_tokens": 700}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "Madar"}
    delays = list(llm.RETRY_DELAYS)
    while True:
        status, text = llm._send(payload, headers)
        if status == 429 and delays:
            llm.time.sleep(delays.pop(0))
            continue
        break
    if status == 429:
        raise llm.LLMError("The AI service is rate limiting requests. Try again in a minute.")
    if status != 200:
        raise llm.LLMError(f"The AI service answered with status {status}.")
    try:
        message = json.loads(text)["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise llm.LLMError("The AI service sent an answer in an unexpected format.") from e
    if not isinstance(message, dict):
        raise llm.LLMError("The AI service sent an answer in an unexpected format.")
    return message


# ---------------------------------------------------------------- helpers (all numbers come from Python)

def _teacher(db, tid):
    return db.execute("""SELECT t.id, t.name, t.subject_id, s.name AS subject FROM teachers t
                         JOIN subjects s ON s.id = t.subject_id WHERE t.id = ?""", (tid,)).fetchone()


def _class_names(db, ids):
    rows = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM classes")}
    return [rows[i] for i in ids if i in rows]


def _weekly_need(db, tid) -> int:
    """Lessons a teacher must give per week = subject hours of their subject in each of their classes."""
    row = db.execute("""SELECT COALESCE(SUM(h.per_week), 0) AS n FROM teacher_classes tc
                        JOIN teachers t ON t.id = tc.teacher_id JOIN classes c ON c.id = tc.class_id
                        JOIN subject_hours h ON h.grade = c.grade AND h.subject_id = t.subject_id
                        WHERE tc.teacher_id = ?""", (tid,)).fetchone()
    return row["n"]


def _unavailable(db, tid) -> set:
    out = set()
    for r in db.execute("SELECT params FROM rules WHERE kind = 'teacher_unavailable'"):
        p = json.loads(r["params"])
        if p.get("teacher_id") == tid:
            out.add((p["day"], p["period"]))
    return out


def _err(message: str) -> dict:
    return {"ok": False, "error": message}


# ---------------------------------------------------------------- tools

class Run:
    """State of one agent request: the database, the proposals so far, and the steps shown to the user."""

    def __init__(self, db: sqlite3.Connection, arabic: bool):
        self.db, self.arabic = db, arabic
        self.proposals: list[dict] = []
        self.steps: list[dict] = []
        self.subjects = db.execute("SELECT id, name, name_ar FROM subjects ORDER BY id").fetchall()
        # full name -> short name, longest first, so nothing longer than "first name + initial" reaches the AI
        names = {r["name"] for r in db.execute("SELECT name FROM teachers")}
        self._short = sorted(((n, short_name(n)) for n in names if short_name(n) != n), key=lambda x: -len(x[0]))

    def display(self, name: str) -> str:
        """A teacher's name in the answer's language (English spelling for English answers)."""
        return name if self.arabic else (english_name(name) or name)

    def for_ai(self, text: str) -> str:
        """Privacy net for everything sent to the model (CONTRACT: only shortened teacher names)."""
        for full, short in self._short:
            text = text.replace(full, short)
        return text

    def _subject(self, sid):
        r = next((s for s in self.subjects if s["id"] == sid), None)
        return None if r is None else ((r["name_ar"] or r["name"]) if self.arabic else r["name"])

    # ---- look-ups ----
    def find_teachers(self, name: str = "", subject: str = ""):
        sid = normalize.subject_id(subject, self.subjects) if subject else None
        if subject and sid is None:
            return _err(f"Unknown subject '{subject}'.")
        words = normalize.key(name).split()
        latin = [w for w in words if re.fullmatch(r"[a-z0-9.()]+", w)]
        rows = self.db.execute("""SELECT t.id, t.name, s.name AS subject, t.subject_id FROM teachers t
                                  JOIN subjects s ON s.id = t.subject_id ORDER BY t.subject_id, t.id""").fetchall()
        links = {}
        for r in self.db.execute("""SELECT tc.teacher_id, c.name FROM teacher_classes tc JOIN classes c ON c.id = tc.class_id
                                    ORDER BY c.grade, c.id"""):
            links.setdefault(r["teacher_id"], []).append(r["name"])
        def matches(r):
            if all(w in normalize.key(r["name"]) for w in words):
                return True
            en_words = [w for w in re.split(r"[\s.()]+", (english_name(r["name"]) or "").lower()) if w]
            return (bool(latin) and len(latin) == len(words)       # each typed word starts a word of the English name
                    and all(any(e.startswith(w.strip(".()")) for e in en_words) for w in latin))

        found = [{"id": r["id"], "name": short_name(r["name"]), "name_en": english_name(r["name"]), "subject": r["subject"],
                  "classes": links.get(r["id"], [])}
                 for r in rows if (sid is None or r["subject_id"] == sid) and matches(r)]
        if not found and words:
            return {"ok": True, "teachers": [], "note": "No name matched. Names are stored in Arabic with English spellings "
                                                        "(first name + initial). Try a subject filter to see the list."}
        return {"ok": True, "teachers": found}

    def get_timetable(self, class_id: int | None = None, teacher_id: int | None = None):
        if (class_id is None) == (teacher_id is None):
            return _err("Give exactly one of class_id or teacher_id.")
        if class_id is not None and not self.db.execute("SELECT 1 FROM classes WHERE id = ?", (class_id,)).fetchone():
            return _err(f"There is no class with id {class_id}.")
        if teacher_id is not None and _teacher(self.db, teacher_id) is None:
            return _err(f"There is no teacher with id {teacher_id}.")
        col, val = ("class_id", class_id) if class_id is not None else ("teacher_id", teacher_id)
        rows = self.db.execute(f"""SELECT l.day, l.period, c.id AS class_id, c.name AS class, t.name AS teacher, s.name AS subject
                                   FROM lessons l JOIN classes c ON c.id = l.class_id JOIN teachers t ON t.id = l.teacher_id
                                   JOIN subjects s ON s.id = l.subject_id WHERE l.{col} = ? ORDER BY l.day, l.period""",
                               (val,)).fetchall()
        if not rows and not self.db.execute("SELECT 1 FROM lessons LIMIT 1").fetchone():
            return {"ok": True, "lessons": [], "note": "No timetable has been generated yet."}
        lessons = [{"day": r["day"], "period": r["period"], "class_id": r["class_id"], "class": r["class"],
                    "subject": r["subject"], "teacher": short_name(r["teacher"]), "teacher_en": english_name(r["teacher"])}
                   for r in rows]
        out = {"ok": True, "lessons": lessons}
        if teacher_id is not None:
            out["per_day"] = [sum(1 for r in rows if r["day"] == d) for d in range(5)]
            out["unavailable"] = sorted([{"day": d, "period": p} for d, p in _unavailable(self.db, teacher_id)],
                                        key=lambda x: (x["day"], x["period"]))
            out["classes"] = sorted({(r["class_id"], r["class"]) for r in rows})
            out["classes"] = [{"id": i, "name": n} for i, n in out["classes"]]
        return out

    def list_rules(self, teacher_id: int | None = None):
        rules = []
        for r in self.db.execute("SELECT id, kind, params, source_text FROM rules ORDER BY id"):
            p = json.loads(r["params"])
            if teacher_id is not None and p.get("teacher_id") != teacher_id:
                continue
            rules.append({"id": r["id"], "kind": r["kind"], "params": p, "note": r["source_text"]})
        return {"ok": True, "rules": rules[:120], "total": len(rules)}

    def find_cover(self, teacher_id: int, day: int):
        if _teacher(self.db, teacher_id) is None:
            return _err(f"There is no teacher with id {teacher_id}.")
        if not 0 <= day <= 4:
            return _err("day must be 0 (Sunday) to 4 (Thursday).")
        if not self.db.execute("SELECT 1 FROM lessons LIMIT 1").fetchone():
            return _err("There is no timetable yet, so there are no lessons to cover. Generate one first.")
        items = find_affected(self.db, teacher_id, day)
        for item in items:
            for s in item["substitutes"]:
                s["name_en"] = english_name(s["name"])
                s["name"] = short_name(s["name"])
        return {"ok": True, "lessons": items}

    def get_slot(self, day: int, period: int, class_id: int | None = None):
        if not (0 <= day <= 4 and 1 <= period <= 7):
            return _err("day must be 0 to 4 and period 1 to 7.")
        if class_id is not None and not self.db.execute("SELECT 1 FROM classes WHERE id = ?", (class_id,)).fetchone():
            return _err(f"There is no class with id {class_id}.")
        if not self.db.execute("SELECT 1 FROM lessons LIMIT 1").fetchone():
            return _err("There is no timetable yet. Generate one first.")
        rows = self.db.execute(f"""SELECT c.id AS class_id, c.name AS class, s.id AS subject_id, s.name AS subject,
                                          t.id AS teacher_id, t.name AS teacher
                                   FROM lessons l JOIN classes c ON c.id = l.class_id JOIN subjects s ON s.id = l.subject_id
                                   JOIN teachers t ON t.id = l.teacher_id WHERE l.day = ? AND l.period = ?
                                   {"AND l.class_id = ?" if class_id is not None else ""} ORDER BY c.grade, c.id""",
                               (day, period, *([class_id] if class_id is not None else []))).fetchall()
        return {"ok": True, "day": DAYS[day], "period": period,
                "lessons": [{**dict(r), "teacher": short_name(r["teacher"]), "teacher_en": english_name(r["teacher"])}
                            for r in rows]}

    def who_is_free(self, day: int, period: int, subject_id: int | None = None):
        if not (0 <= day <= 4 and 1 <= period <= 7):
            return _err("day must be 0 to 4 and period 1 to 7.")
        if subject_id is not None and self._subject_en(subject_id) is None:
            return _err(f"There is no subject with id {subject_id}.")
        if not self.db.execute("SELECT 1 FROM lessons LIMIT 1").fetchone():
            return _err("There is no timetable yet. Generate one first.")
        busy = {r["teacher_id"] for r in self.db.execute("SELECT teacher_id FROM lessons WHERE day = ? AND period = ?", (day, period))}
        load = {r["teacher_id"]: r["n"] for r in self.db.execute(
            "SELECT teacher_id, COUNT(*) AS n FROM lessons WHERE day = ? GROUP BY teacher_id", (day,))}
        blocked = set()
        for r in self.db.execute("SELECT params FROM rules WHERE kind = 'teacher_unavailable'"):
            p = json.loads(r["params"])
            if p.get("day") == day and p.get("period") == period:
                blocked.add(p.get("teacher_id"))
        free = []
        for t in self.db.execute("""SELECT t.id, t.name, t.subject_id, s.name AS subject FROM teachers t
                                    JOIN subjects s ON s.id = t.subject_id ORDER BY t.id"""):
            if t["id"] in busy or t["id"] in blocked:
                continue
            free.append({"teacher_id": t["id"], "name": short_name(t["name"]), "name_en": english_name(t["name"]),
                         "subject": t["subject"],
                         "same_subject": subject_id is not None and t["subject_id"] == subject_id,
                         "lessons_that_day": load.get(t["id"], 0)})
        # same ranking as POST /api/absences: same subject first, then the lightest day, then id
        free.sort(key=lambda x: (not x["same_subject"], x["lessons_that_day"], x["teacher_id"]))
        return {"ok": True, "day": DAYS[day], "period": period, "free_count": len(free), "teachers": free[:12]}

    # ---- proposals (validated, never saved) ----
    def propose_rule(self, kind: str, reason: str = "", **fields):
        keys = {"subject_not_in_period": ("subject_id", "period"),
                "teacher_unavailable": ("teacher_id", "day", "period"),
                "pin_lesson": ("class_id", "subject_id", "day", "period")}.get(kind)
        if keys is None:
            return _err("kind must be subject_not_in_period, teacher_unavailable or pin_lesson.")
        params = {k: fields.get(k) for k in keys}
        try:
            validated = parse_params(kind, params)                      # same check as POST /api/rules
        except ValueError as why:
            return _err(f"The rule is not valid: {why}")
        try:
            check_things_exist(self.db, kind, validated)                # same check as POST /api/rules
        except ApiError as e:
            return _err(e.message)
        params = validated.model_dump()
        for other in self.db.execute("SELECT params FROM rules WHERE kind = ?", (kind,)):
            if json.loads(other["params"]) == params:
                return _err("That rule is already saved.")
        for p in self.proposals:
            if p["type"] == "rule" and p["request"]["body"]["kind"] == kind and p["request"]["body"]["params"] == params:
                return {"ok": True, "id": p["id"], "note": "Already proposed."}

        impact = self._rule_impact(kind, params)
        note = (reason or "").strip()[:200] or "Proposed by the Madar assistant"
        description = explain(self.db, kind, params, self.arabic)
        if kind == "teacher_unavailable":
            stored = _teacher(self.db, params["teacher_id"])["name"]
            description = description.replace(stored, _iso(self.display(stored)))
        return self._add("rule", {"method": "POST", "path": "/api/rules",
                                  "body": {"kind": kind, "params": params, "source_text": note}},
                         description, impact)

    def _rule_impact(self, kind, p) -> list[dict]:
        db, out = self.db, []
        if kind == "teacher_unavailable":
            now = db.execute("""SELECT c.name, s.name AS subject FROM lessons l JOIN classes c ON c.id = l.class_id
                                JOIN subjects s ON s.id = l.subject_id WHERE l.teacher_id = ? AND l.day = ? AND l.period = ?""",
                             (p["teacher_id"], p["day"], p["period"])).fetchone()
            if now:
                out.append({"level": "info", "text": f"Today this slot has {now['subject']} in class {now['name']}; "
                                                      "that lesson moves when the timetable is generated again."})
            blocked = _unavailable(db, p["teacher_id"]) | {(p["day"], p["period"])}
            need, free = _weekly_need(db, p["teacher_id"]), SLOTS_PER_WEEK - len(blocked)
            level = "error" if need > free else "info"
            out.append({"level": level, "text": f"Teacher load: {need} lessons a week, {free} free slots after this rule"
                        + (" — Generate will fail (teacher_overloaded)." if need > free else ".")})
        elif kind == "subject_not_in_period":
            n = db.execute("SELECT COUNT(*) AS n FROM lessons WHERE subject_id = ? AND period = ?",
                           (p["subject_id"], p["period"])).fetchone()["n"]
            if n:
                out.append({"level": "info", "text": f"{n} lessons of this subject are in period {p['period']} now; "
                                                     "they move when the timetable is generated again."})
        else:  # pin_lesson
            now = db.execute("""SELECT s.name AS subject FROM lessons l JOIN subjects s ON s.id = l.subject_id
                                WHERE l.class_id = ? AND l.day = ? AND l.period = ?""",
                             (p["class_id"], p["day"], p["period"])).fetchone()
            if now and now["subject"] != self._subject_en(p["subject_id"]):
                out.append({"level": "info", "text": f"That slot has {now['subject']} now; it moves on the next Generate."})
        return out

    def _subject_en(self, sid):
        return next((s["name"] for s in self.subjects if s["id"] == sid), None)

    def propose_new_teacher(self, name: str, subject_id: int, class_ids: list, reason: str = ""):
        name = (name or "").strip()
        if not name or len(name) > 100:
            return _err("name must be 1 to 100 characters.")
        if self._subject_en(subject_id) is None:
            return _err(f"There is no subject with id {subject_id}.")
        ids = []
        for c in class_ids or []:
            n = normalize.number(c)
            if n is None:
                return _err("class_ids must be whole numbers.")
            if n not in ids:
                ids.append(n)
        names = _class_names(self.db, ids)
        if len(names) != len(ids):
            return _err("One or more class ids do not exist.")
        # whose classes move (code-computed, so the preview cannot misstate it)
        takeover = {}
        if ids:
            marks = ",".join("?" * len(ids))
            for r in self.db.execute(f"""SELECT t.name, c.name AS class FROM teacher_classes tc
                                         JOIN teachers t ON t.id = tc.teacher_id JOIN classes c ON c.id = tc.class_id
                                         WHERE tc.class_id IN ({marks}) AND t.subject_id = ?""", [*ids, subject_id]):
                takeover.setdefault(r["name"], []).append(r["class"])
        hours = {(r["grade"], r["subject_id"]): r["per_week"] for r in self.db.execute("SELECT * FROM subject_hours")}
        grades = {r["id"]: r["grade"] for r in self.db.execute("SELECT id, grade FROM classes")}
        load = sum(hours.get((grades[i], subject_id), 0) for i in ids)

        subject = self._subject(subject_id)
        if self.arabic:
            desc = f"إضافة {_iso(name)} معلمةً لمادة {subject}" + (f" في الفصول {'، '.join(names)}" if names else "") + "."
        else:
            desc = f"Add {_iso(name)} to teach {subject}" + (f" in classes {', '.join(names)}" if names else "") + "."
        impact = [{"level": "info", "text": f"Takes over from {_iso(self.display(who))}: {', '.join(cls)}."}
                  for who, cls in takeover.items()]
        impact.append({"level": "error" if load > SLOTS_PER_WEEK else "info",
                       "text": f"New teacher's load: {load} lessons a week."})
        note = {"reason": (reason or "").strip()[:200]}
        return self._add("teacher", {"method": "POST", "path": "/api/teachers",
                                     "body": {"name": name, "subject_id": subject_id, "class_ids": ids}},
                         desc, impact, extra=note)

    def _add(self, kind, request, description, impact, extra=None):
        pid = f"P{len(self.proposals) + 1}"
        self.proposals.append({"id": pid, "type": kind, "description": description, "impact": impact,
                               "request": request, **(extra or {})})
        return {"ok": True, "id": pid, "description": description, "impact": [i["text"] for i in impact]}


TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


def _step_summary(run: Run, name: str, args: dict, result: dict) -> str:
    """A short line for the 'how I worked it out' list in the app."""
    def tname(tid):
        t = _teacher(run.db, tid) if isinstance(tid, int) else None
        return _iso(run.display(t["name"])) if t else f"#{tid}"
    if not result.get("ok", True):
        return f"{name}: {result.get('error', 'failed')}"
    if name == "find_teachers":
        return f"Looked up teachers ({len(result.get('teachers', []))} found)"
    if name == "get_timetable":
        who = f"class {', '.join(_class_names(run.db, [args.get('class_id')]))}" if args.get("class_id") is not None \
            else tname(args.get("teacher_id"))
        return f"Read the week of {who} ({len(result.get('lessons', []))} lessons)"
    if name == "list_rules":
        return f"Read saved rules ({result.get('total', 0)})"
    if name == "find_cover":
        return f"Found cover options for {tname(args.get('teacher_id'))} on {DAYS[args.get('day', 0)]}"
    if name == "get_slot":
        where = f" for class {', '.join(_class_names(run.db, [args.get('class_id')]))}" if args.get("class_id") is not None else ""
        return f"Read {DAYS[args.get('day', 0)]}, period {args.get('period')}{where} ({len(result.get('lessons', []))} lessons)"
    if name == "who_is_free":
        return f"Found {result.get('free_count', 0)} teachers free on {DAYS[args.get('day', 0)]}, period {args.get('period')}"
    if name in ("propose_rule", "propose_new_teacher"):
        return f"Prepared proposal {result.get('id')}"
    return name


def run_agent(db: sqlite3.Connection, message: str, language: str = "en", history: list[dict] | None = None) -> dict:
    """Answer one request. Returns {"reply", "proposals", "steps"}. Raises ApiError (503 ai_unavailable)."""
    message = (message or "").strip()
    if not message:
        raise ApiError(422, "invalid_request", "message: must not be empty")
    arabic = language == "ar" or bool(re.search("[؀-ۿ]", message))
    run = Run(db, arabic)
    classes = db.execute("SELECT id, name FROM classes ORDER BY grade, id").fetchall()
    system = SYSTEM.format(
        language="Arabic" if arabic else "English",
        subjects="; ".join(f"{s['id']}: {s['name']} / {s['name_ar']}" for s in run.subjects),
        classes=", ".join(f"{c['id']}: {c['name']}" for c in classes))
    messages = [{"role": "system", "content": system}]
    for turn in (history or [])[-6:]:
        if turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
            messages.append({"role": turn["role"], "content": run.for_ai(turn["content"][:2000])})
    messages.append({"role": "user", "content": run.for_ai(message)})

    reply = ""
    try:
        for step in range(MAX_STEPS):
            answer = _call_model(messages, allow_tools=step < MAX_STEPS - 1)
            calls = answer.get("tool_calls") or []
            if not calls:
                reply = (answer.get("content") or "").strip()
                break
            messages.append({"role": "assistant", "content": answer.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = (call.get("function") or {})
                name = fn.get("name")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError
                except ValueError:
                    result, args = _err("The tool arguments were not valid JSON."), {}
                else:
                    if name not in TOOL_NAMES:
                        result = _err(f"There is no tool called {name}.")
                    else:
                        try:
                            result = getattr(run, name)(**args)
                        except TypeError as e:  # unexpected or missing argument names
                            result = _err(f"Wrong arguments for {name}: {e}")
                run.steps.append({"tool": name, "summary": _step_summary(run, name, args, result)})
                content = run.for_ai(json.dumps(result, ensure_ascii=False))
                if len(content) > MAX_TOOL_RESULT:
                    content = content[:MAX_TOOL_RESULT] + '..." (cut: ask for something narrower)'
                messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": content})
    except llm.LLMError as e:
        if not run.steps:
            raise ApiError(503, "ai_unavailable", str(e)) from e
        reply = ""  # the AI failed half way: still return what was prepared
    if not reply:
        reply = ("لم أتمكن من إكمال الطلب. يمكنك مراجعة ما تم تجهيزه أدناه أو إعادة صياغة الطلب." if arabic
                 else "I couldn't finish this request. Review anything prepared below, or rephrase the request.")
    return {"reply": reply, "proposals": run.proposals, "steps": run.steps}
