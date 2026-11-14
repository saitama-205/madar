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
