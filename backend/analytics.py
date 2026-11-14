"""Metrics about the saved timetable. Everything here is computed in Python from the `lessons` table;
the AI never calculates (it only explains these numbers, see ai/insights.py).

Based on the old project's timetable_audit.py (re-count everything from the saved lessons, do not trust the solver),
plus the workload numbers: lessons per teacher / class per day, and teachers' gaps between lessons."""
import json
import sqlite3

from ai.privacy import short_name
from errors import ApiError
from solver import PARALLEL_CAP, TWO_PER_DAY

DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"]
HARD_SUBJECTS = ["Arabic", "English", "Math", "Science"]
MAX_VIOLATIONS = 50


def _per_day(days: list[int]) -> list[int]:
    return [days.count(d) for d in range(5)]


def compute(db: sqlite3.Connection) -> dict:
    lessons = db.execute("""SELECT l.class_id, l.teacher_id, l.subject_id, l.day, l.period,
                                   c.name AS class, c.grade, s.name AS subject
                            FROM lessons l JOIN classes c ON c.id = l.class_id JOIN subjects s ON s.id = l.subject_id
                            ORDER BY l.day, l.period""").fetchall()
    if not lessons:
        raise ApiError(409, "no_timetable", "There is no timetable yet. Generate one first.")
    teachers = db.execute("""SELECT t.id, t.name, t.subject_id, s.name AS subject FROM teachers t
                             JOIN subjects s ON s.id = t.subject_id ORDER BY t.id""").fetchall()
    classes = db.execute("""SELECT id, name, grade FROM classes
                            ORDER BY grade, CAST(substr(name, 1, instr(name, '/') - 1) AS INTEGER)""").fetchall()

    by_teacher: dict[int, list] = {t["id"]: [] for t in teachers}
    by_class: dict[int, list] = {c["id"]: [] for c in classes}
    for l in lessons:
        by_teacher.setdefault(l["teacher_id"], []).append(l)
        by_class.setdefault(l["class_id"], []).append(l)

    teacher_load = [{"teacher_id": t["id"], "teacher": t["name"], "subject": t["subject"],
                     "per_week": len(by_teacher[t["id"]]), "per_day": _per_day([l["day"] for l in by_teacher[t["id"]]])}
                    for t in teachers]

    teacher_gaps = []
    for t in teachers:
        for day in range(5):
            periods = sorted(l["period"] for l in by_teacher[t["id"]] if l["day"] == day)
            gap = (periods[-1] - periods[0] + 1 - len(periods)) if periods else 0
            if gap > 0:
                teacher_gaps.append({"teacher_id": t["id"], "teacher": t["name"], "day": day, "gap_periods": gap})

    names = {r["name"] for r in db.execute("SELECT name FROM subjects")}
    hard = {name: [0] * 7 for name in HARD_SUBJECTS if name in names}
    for l in lessons:
        if l["subject"] in hard:
            hard[l["subject"]][l["period"] - 1] += 1

    class_load = [{"class_id": c["id"], "class": c["name"], "per_day": _per_day([l["day"] for l in by_class[c["id"]]])}
                  for c in classes]

    violations = _rule_violations(db, lessons, teachers, classes)
    shown = violations[:MAX_VIOLATIONS]
    if len(violations) > MAX_VIOLATIONS:
        shown.append(f"... and {len(violations) - MAX_VIOLATIONS} more.")
    return {"teacher_load": teacher_load, "teacher_gaps": teacher_gaps, "hard_subjects_by_period": hard,
            "class_load": class_load, "rule_check": {"ok": not violations, "violations": shown}}


def _rule_violations(db, lessons, teachers, classes) -> list[str]:
    """Re-check the contract's hard rules against the saved lessons. Teacher names are shortened in the sentences."""
    out: list[str] = []
    tname = {t["id"]: short_name(t["name"]) for t in teachers}
    subject_name = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM subjects")}
    day = lambda d: DAYS[d]

    # 1. every class has exactly one lesson in every slot
    slot_count: dict[tuple, int] = {}
    for l in lessons:
        slot_count[l["class_id"], l["day"], l["period"]] = slot_count.get((l["class_id"], l["day"], l["period"]), 0) + 1
    for c in classes:
        for d in range(5):
            for p in range(1, 8):
                n = slot_count.get((c["id"], d, p), 0)
                if n != 1:
                    out.append(f"Class {c['name']} has {n} lessons on {day(d)} period {p} (it must have exactly 1).")

    # 2. a teacher is never in two places at once
    seen: dict[tuple, list] = {}
    for l in lessons:
        seen.setdefault((l["teacher_id"], l["day"], l["period"]), []).append(l["class"])
    for (tid, d, p), where in seen.items():
        if len(where) > 1:
            out.append(f"{tname.get(tid, tid)} is in {' and '.join(where)} on {day(d)} period {p}.")

    # 3. each class gets exactly subject_hours.per_week lessons of each subject
    want = {(r["grade"], r["subject_id"]): r["per_week"] for r in db.execute("SELECT grade, subject_id, per_week FROM subject_hours")}
    have: dict[tuple, int] = {}
    for l in lessons:
        have[l["class_id"], l["subject_id"]] = have.get((l["class_id"], l["subject_id"]), 0) + 1
    for c in classes:
        for sid, name in subject_name.items():
            w, h = want.get((c["grade"], sid), 0), have.get((c["id"], sid), 0)
            if w != h:
                out.append(f"Class {c['name']} has {h} {name} lessons a week; the study plan says {w}.")

    # 4. the lesson's teacher is the one assigned to that class (and teaches that subject)
    assigned = {(r["teacher_id"], r["class_id"]) for r in db.execute("SELECT teacher_id, class_id FROM teacher_classes")}
    tsubject = {t["id"]: t["subject_id"] for t in teachers}
    for l in lessons:
        if (l["teacher_id"], l["class_id"]) not in assigned or tsubject.get(l["teacher_id"]) != l["subject_id"]:
            out.append(f"{l['subject']} in class {l['class']} on {day(l['day'])} period {l['period']} "
                       f"is taught by {tname.get(l['teacher_id'], l['teacher_id'])}, who is not assigned to it.")

    # 5. saved rules
    for r in db.execute("SELECT kind, params FROM rules"):
        p = json.loads(r["params"])
        if r["kind"] == "subject_not_in_period":
            for l in lessons:
                if l["subject_id"] == p["subject_id"] and l["period"] == p["period"]:
                    out.append(f"{l['subject']} is in period {p['period']} for class {l['class']} on {day(l['day'])} (rule: never).")
        elif r["kind"] == "teacher_unavailable":
            for l in lessons:
                if l["teacher_id"] == p["teacher_id"] and l["day"] == p["day"] and l["period"] == p["period"]:
                    out.append(f"{tname.get(l['teacher_id'])} teaches on {day(p['day'])} period {p['period']} (rule: unavailable).")
        elif r["kind"] == "pin_lesson":
            hit = any(l["class_id"] == p["class_id"] and l["day"] == p["day"] and l["period"] == p["period"]
                      and l["subject_id"] == p["subject_id"] for l in lessons)
            if not hit:
                cname = next((c["name"] for c in classes if c["id"] == p["class_id"]), p["class_id"])
                out.append(f"Class {cname} should have {subject_name.get(p['subject_id'])} on {day(p['day'])} period {p['period']} (rule: pinned).")

    # 6. daily cap per class and subject
    per_day: dict[tuple, int] = {}
    for l in lessons:
        k = (l["class_id"], l["subject_id"], l["day"])
        per_day[k] = per_day.get(k, 0) + 1
    cname = {c["id"]: c["name"] for c in classes}
    for (cid, sid, d), n in per_day.items():
        cap = 2 if subject_name[sid] in TWO_PER_DAY else 1
        if n > cap:
            out.append(f"Class {cname[cid]} has {n} {subject_name[sid]} lessons on {day(d)} (limit {cap}).")

    # 7. parallel cap per subject and slot
    parallel: dict[tuple, int] = {}
    for l in lessons:
        parallel[l["subject"], l["day"], l["period"]] = parallel.get((l["subject"], l["day"], l["period"]), 0) + 1
    for (name, d, p), n in parallel.items():
        cap = PARALLEL_CAP.get(name)
        if cap and n > cap:
            out.append(f"{n} classes have {name} on {day(d)} period {p} (limit {cap}).")
    return out
