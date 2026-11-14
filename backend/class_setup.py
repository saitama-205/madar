"""Automatic setup of a newly added class: a teacher for every subject the class has lessons in.

Rules (simplest reasonable choice):
  1. Candidates are the teachers of that subject.
  2. Prefer teachers who already teach that subject in the same grade, then any other teacher of the subject.
  3. Within a group pick the lowest weekly load that still has room for this class's lessons. Room = the solver's
     own limit: 35 slots minus the slots the teacher is unavailable (saved teacher_unavailable rules).
  4. If nobody has room, pick the least loaded teacher of that subject and flag it (over_capacity: true).
     Generation will then refuse with teacher_overloaded and say who, instead of building a broken timetable.
  5. If the school has no teacher of that subject at all, nothing is assigned (the class is skipped by Generate)."""
import json
import sqlite3

from solver import SLOTS_PER_WEEK


def weekly_loads(db: sqlite3.Connection) -> dict[int, int]:
    """teacher_id -> lessons per week, counted exactly like the solver does (hours of the subject for each class)."""
    rows = db.execute("""SELECT tc.teacher_id, SUM(h.per_week) AS load
                         FROM teacher_classes tc
                         JOIN teachers t ON t.id = tc.teacher_id
                         JOIN classes c ON c.id = tc.class_id
                         JOIN subject_hours h ON h.grade = c.grade AND h.subject_id = t.subject_id
                         GROUP BY tc.teacher_id""")
    return {r["teacher_id"]: r["load"] for r in rows}


def capacities(db: sqlite3.Connection) -> dict[int, int]:
    """teacher_id -> most lessons per week the solver allows (35 minus unavailable slots)."""
    blocked: dict[int, set] = {}
    for r in db.execute("SELECT params FROM rules WHERE kind = 'teacher_unavailable'"):
        p = json.loads(r["params"])
        blocked.setdefault(p["teacher_id"], set()).add((p["day"], p["period"]))
    return {r["id"]: SLOTS_PER_WEEK - len(blocked.get(r["id"], ())) for r in db.execute("SELECT id FROM teachers")}


def auto_assign_teachers(db: sqlite3.Connection, class_id: int, grade: int) -> list[dict]:
    """Insert teacher_classes rows for the class (caller commits) and describe each choice."""
    load, cap = weekly_loads(db), capacities(db)
    same_grade = {r["teacher_id"] for r in db.execute(
        """SELECT DISTINCT tc.teacher_id FROM teacher_classes tc JOIN classes c ON c.id = tc.class_id
           WHERE c.grade = ? AND tc.class_id != ?""", (grade, class_id))}
    teachers = db.execute("SELECT id, name, subject_id FROM teachers ORDER BY id").fetchall()
    subjects = db.execute("""SELECT s.id, s.name, h.per_week FROM subject_hours h JOIN subjects s ON s.id = h.subject_id
                             WHERE h.grade = ? AND h.per_week > 0 ORDER BY s.id""", (grade,)).fetchall()

    result = []
    for s in subjects:
        pool = [t for t in teachers if t["subject_id"] == s["id"]]
        entry = {"subject_id": s["id"], "subject": s["name"], "per_week": s["per_week"], "teacher_id": None,
                 "teacher": None, "load_after": None, "capacity": None, "over_capacity": False, "same_grade": False}
        if not pool:
            result.append(entry)
            continue

        def fits(t):
            return load.get(t["id"], 0) + s["per_week"] <= cap[t["id"]]

        def by_load(t):
            return (load.get(t["id"], 0), t["id"])

        preferred = [t for t in pool if t["id"] in same_grade and fits(t)]
        others = [t for t in pool if t["id"] not in same_grade and fits(t)]
        if preferred:
            pick = min(preferred, key=by_load)
        elif others:
            pick = min(others, key=by_load)
        else:
            pick = min(pool, key=by_load)
            entry["over_capacity"] = True
        load[pick["id"]] = load.get(pick["id"], 0) + s["per_week"]
        db.execute("INSERT OR IGNORE INTO teacher_classes (teacher_id, class_id) VALUES (?, ?)", (pick["id"], class_id))
        entry.update(teacher_id=pick["id"], teacher=pick["name"], load_after=load[pick["id"]], capacity=cap[pick["id"]],
                     same_grade=pick["id"] in same_grade)
        result.append(entry)
    return result
