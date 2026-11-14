"""Who can cover an absent teacher's lessons. Plain rules, no AI (the AI only words the explanation afterwards).

Ranking, best first:
  1. a teacher of the same subject who is free in that slot ("same_subject_free")
  2. any other teacher who is free in that slot ("free_only": can supervise, may not know the material)
Within each tier the teacher with the fewest lessons that day comes first, then the lower id (so results are stable).
"Free" = no lesson in that slot AND no saved teacher_unavailable rule for that slot."""
import json
import sqlite3

MAX_SUBSTITUTES = 3


def find_affected(db: sqlite3.Connection, teacher_id: int, day: int, max_substitutes: int = MAX_SUBSTITUTES) -> list[dict]:
    teachers = db.execute("SELECT id, name, subject_id FROM teachers ORDER BY id").fetchall()
    busy = set()       # (teacher_id, period) with a lesson that day
    day_load = {}      # teacher_id -> lessons that day
    for r in db.execute("SELECT teacher_id, period FROM lessons WHERE day = ?", (day,)):
        busy.add((r["teacher_id"], r["period"]))
        day_load[r["teacher_id"]] = day_load.get(r["teacher_id"], 0) + 1
    blocked = set()    # (teacher_id, period) the teacher cannot teach that day
    for r in db.execute("SELECT params FROM rules WHERE kind = 'teacher_unavailable'"):
        p = json.loads(r["params"])
        if p["day"] == day:
            blocked.add((p["teacher_id"], p["period"]))

    lessons = db.execute("""SELECT l.period, l.class_id, c.name AS class, l.subject_id, s.name AS subject, s.name_ar AS subject_ar
                            FROM lessons l JOIN classes c ON c.id = l.class_id JOIN subjects s ON s.id = l.subject_id
                            WHERE l.teacher_id = ? AND l.day = ? ORDER BY l.period, c.grade, c.id""",
                         (teacher_id, day)).fetchall()
    affected = []
    for lesson in lessons:
        period = lesson["period"]
        candidates = []
        for t in teachers:
            if t["id"] == teacher_id or (t["id"], period) in busy or (t["id"], period) in blocked:
                continue
            same = t["subject_id"] == lesson["subject_id"]
            candidates.append({"teacher_id": t["id"], "name": t["name"],
                               "reason": "same_subject_free" if same else "free_only",
                               "day_load": day_load.get(t["id"], 0)})
        candidates.sort(key=lambda c: (c["reason"] != "same_subject_free", c["day_load"], c["teacher_id"]))
        affected.append({"day": day, "period": period, "class_id": lesson["class_id"], "class": lesson["class"],
                         "subject": lesson["subject"], "subject_ar": lesson["subject_ar"], "substitutes": candidates[:max_substitutes]})
    return affected


def find_long_term(db: sqlite3.Connection, teacher_id: int, max_candidates: int = 5) -> dict:
    """Long-term absence: for each class the absent teacher teaches, who could take the whole subject over.
    A class has one teacher per subject and a teacher teaches one subject, so only teachers of the SAME subject can take
    over. Ranking, best first: has room in their week (own load + this class's hours <= 35 - unavailable slots), then
    fewest clashes with the lessons this class has now (slots where they already teach or are unavailable), then the
    lowest weekly load, then the lower id."""
    from class_setup import capacities, weekly_loads

    absent = db.execute("SELECT id, name, subject_id FROM teachers WHERE id = ?", (teacher_id,)).fetchone()
    subject = db.execute("SELECT name, name_ar FROM subjects WHERE id = ?", (absent["subject_id"],)).fetchone()
    load, cap = weekly_loads(db), capacities(db)
    busy = {}      # teacher_id -> {(day, period)} they teach now
    for r in db.execute("SELECT teacher_id, day, period FROM lessons"):
        busy.setdefault(r["teacher_id"], set()).add((r["day"], r["period"]))
    blocked = {}   # teacher_id -> {(day, period)} unavailable
    for r in db.execute("SELECT params FROM rules WHERE kind = 'teacher_unavailable'"):
        p = json.loads(r["params"])
        blocked.setdefault(p["teacher_id"], set()).add((p["day"], p["period"]))
    others = db.execute("SELECT id, name FROM teachers WHERE subject_id = ? AND id != ? ORDER BY id",
                        (absent["subject_id"], teacher_id)).fetchall()

    assignments, warnings = [], []
    classes = db.execute("""SELECT c.id, c.name, c.grade, COALESCE(h.per_week, 0) AS per_week FROM teacher_classes tc
                            JOIN classes c ON c.id = tc.class_id
                            LEFT JOIN subject_hours h ON h.grade = c.grade AND h.subject_id = ?
                            WHERE tc.teacher_id = ? ORDER BY c.grade, CAST(substr(c.name, 1, instr(c.name, '/') - 1) AS INTEGER)""",
                         (absent["subject_id"], teacher_id)).fetchall()
    for c in classes:
        if c["per_week"] == 0:
            continue
        slots = {(r["day"], r["period"]) for r in db.execute(
            "SELECT day, period FROM lessons WHERE class_id = ? AND teacher_id = ?", (c["id"], teacher_id))}
        candidates = []
        for t in others:
            clashes = len(slots & (busy.get(t["id"], set()) | blocked.get(t["id"], set())))
            after = load.get(t["id"], 0) + c["per_week"]
            candidates.append({"teacher_id": t["id"], "name": t["name"], "reason": "same_subject",
                               "load": load.get(t["id"], 0), "load_after": after, "capacity": cap[t["id"]],
                               "over_capacity": after > cap[t["id"]], "clashes": clashes})
        candidates.sort(key=lambda x: (x["over_capacity"], x["clashes"], x["load"], x["teacher_id"]))
        assignments.append({"class_id": c["id"], "class": c["name"], "subject_id": absent["subject_id"],
                            "subject": subject["name"], "subject_ar": subject["name_ar"], "per_week": c["per_week"],
                            "lessons": [{"day": d, "period": p} for d, p in sorted(slots)],
                            "substitutes": candidates[:max_candidates]})
    if not others:
        warnings.append(f"There is no other {subject['name']} teacher, so nobody can take over these classes.")
    return {"mode": "long", "teacher_id": teacher_id, "teacher": absent["name"], "assignments": assignments,
            "warnings": warnings}
