"""Timetable solver (Google OR-Tools CP-SAT).

It reads the database and nothing else (CONTRACT.md: "the solver only ever reads the database"), checks that a
timetable is even possible, solves, and replaces the `lessons` table in one transaction.

The model has one yes/no variable for every (class, subject, day, period): "does this class have this subject in
this slot?". Because a class has exactly one teacher per subject, the teacher follows from the subject, so hard
rule 4 (the lesson's teacher is the assigned one) holds by construction. All other rules are constraints.
"""
import json
import math
import os
import sqlite3
import threading
import time
from collections import defaultdict

from ortools.sat.python import cp_model

from errors import ApiError
from rule_params import parse_params

DAYS = range(5)  # 0 = Sunday .. 4 = Thursday
PERIODS = range(1, 8)  # 1..7
SLOTS_PER_WEEK = 35

# Contract hard rule 6: lessons of one subject per class per day (default 1).
TWO_PER_DAY = {"Arabic", "Math", "Art", "Music"}
# Contract hard rule 7: at most this many classes may have the subject in the same slot.
PARALLEL_CAP = {"Science": 2, "Computer": 2, "Art": 4, "PE": 4, "Music": 2}

_busy = threading.Lock()  # only one generation at a time


def time_limit_seconds() -> float:
    return float(os.environ.get("MADAR_SOLVER_SECONDS", 30))


def _some(items, limit=3):
    """'A, B, C and 4 more'"""
    items = list(items)
    text = ", ".join(map(str, items[:limit]))
    return text + (f" and {len(items) - limit} more" if len(items) > limit else "")


def section_key(name: str):
    section, grade = name.split("/")
    return int(grade), int(section)


class Problem:
    """Everything the solver needs, read from the database."""

    def __init__(self, db: sqlite3.Connection):
        self.classes = {r["id"]: (r["name"], r["grade"]) for r in db.execute("SELECT id, name, grade FROM classes")}
        self.subjects = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM subjects")}
        self.teachers = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM teachers")}
        self.hours = {(r["grade"], r["subject_id"]): r["per_week"]
                      for r in db.execute("SELECT grade, subject_id, per_week FROM subject_hours WHERE per_week > 0")}
        self.assigned = defaultdict(list)  # (class_id, subject_id) -> [teacher_id]
        for r in db.execute("""SELECT tc.class_id, tc.teacher_id, t.subject_id FROM teacher_classes tc
                               JOIN teachers t ON t.id = tc.teacher_id ORDER BY tc.teacher_id"""):
            self.assigned[(r["class_id"], r["subject_id"])].append(r["teacher_id"])
        self.rules = db.execute("SELECT id, kind, params FROM rules ORDER BY id").fetchall()

        # (class_id, subject_id) -> lessons per week, for every lesson the school needs
        self.needed = {(cid, sid): h for cid, (_, grade) in self.classes.items()
                       for (g, sid), h in self.hours.items() if g == grade}

        self.subject_not_in = defaultdict(set)  # subject_id -> {periods}
        self.unavailable = defaultdict(set)  # teacher_id -> {(day, period)}
        self.pins = []  # (class_id, subject_id, day, period)

    # ----- checks that give a clear message instead of a silent "impossible" -----

    def check_data(self):
        if not self.classes:
            raise ApiError(422, "no_classes", "There are no classes yet, so there is nothing to schedule.")
        for grade in sorted({g for _, g in self.classes.values()}):
            total = sum(h for (g, _), h in self.hours.items() if g == grade)
            if total != SLOTS_PER_WEEK:
                raise ApiError(422, "bad_hours", f"Grade {grade} has {total} lessons per week in the subject hours, "
                                                 f"but every class needs exactly {SLOTS_PER_WEEK}.")
        missing = defaultdict(list)
        for (cid, sid) in sorted(self.needed, key=lambda k: (section_key(self.classes[k[0]][0]), k[1])):
            teachers = self.assigned.get((cid, sid), [])
            if len(teachers) > 1:
                raise ApiError(422, "multiple_teachers", f"Class {self.classes[cid][0]} has more than one teacher for "
                                                         f"{self.subjects[sid]}. A class needs exactly one per subject.")
            if not teachers:
                missing[self.classes[cid][0]].append(self.subjects[sid])
        if missing:
            parts = [f"Class {name} has no teacher for {_some(subjects, 5)}" for name, subjects in missing.items()]
            raise ApiError(422, "missing_teachers", "Cannot generate. " + "; ".join(parts[:3])
                           + (f"; and {len(parts) - 3} more classes" if len(parts) > 3 else "") + ".")

    def parse_rules(self):
        for r in self.rules:
            bad = lambda why: ApiError(422, "invalid_rule", f"Rule {r['id']} ({r['kind']}) cannot be used: {why} "
                                                            "Delete or fix it, then try again.")
            try:
                p = parse_params(r["kind"], json.loads(r["params"]))  # same validation as the rules endpoints
            except ValueError as why:
                raise bad(str(why))
            if r["kind"] == "subject_not_in_period":
                if p.subject_id not in self.subjects:
                    raise bad("that subject does not exist.")
                self.subject_not_in[p.subject_id].add(p.period)
            elif r["kind"] == "teacher_unavailable":
                if p.teacher_id not in self.teachers:
                    raise bad("that teacher does not exist.")
                self.unavailable[p.teacher_id].add((p.day, p.period))
            else:  # pin_lesson
                if (p.class_id, p.subject_id) not in self.needed:
                    raise bad("that class does not have that subject.")
                self.pins.append((p.class_id, p.subject_id, p.day, p.period))

    def check_teacher_loads(self):
        load = defaultdict(int)
        for (cid, sid), h in self.needed.items():
            load[self.assigned[(cid, sid)][0]] += h
        for tid, lessons in load.items():
            free = SLOTS_PER_WEEK - len(self.unavailable.get(tid, ()))
            if lessons > free:
                raise ApiError(422, "teacher_overloaded", f"Teacher {self.teachers[tid]} has {lessons} lessons per week "
                                                          f"but only {free} free slots. Add a teacher for some of "
                                                          "their classes or remove an unavailability rule.")


def solve(problem: Problem, seconds: float):
    """Returns [(class_id, teacher_id, subject_id, day, period)]."""
    model = cp_model.CpModel()
    x = {}  # (class, subject, day, period) -> BoolVar
    for (cid, sid) in problem.needed:
        for d in DAYS:
            for p in PERIODS:
                x[cid, sid, d, p] = model.NewBoolVar(f"x_{cid}_{sid}_{d}_{p}")

    # Rule 1: every class has exactly one lesson in every slot.
    for cid in problem.classes:
        for d in DAYS:
            for p in PERIODS:
                model.AddExactlyOne(x[cid, sid, d, p] for (c, sid) in problem.needed if c == cid)

    # Rule 3: each class gets exactly per_week lessons of each subject.
    # Rule 6: and at most N of them on one day (never less than needed to fit the week).
    for (cid, sid), hours in problem.needed.items():
        model.Add(sum(x[cid, sid, d, p] for d in DAYS for p in PERIODS) == hours)
        cap = max(2 if problem.subjects[sid] in TWO_PER_DAY else 1, math.ceil(hours / len(DAYS)))
        for d in DAYS:
            model.Add(sum(x[cid, sid, d, p] for p in PERIODS) <= cap)

    # Rule 2: a teacher is never in two places at once.
    by_teacher = defaultdict(list)
    for (cid, sid) in problem.needed:
        by_teacher[problem.assigned[(cid, sid)][0]].append((cid, sid))
    for tid, pairs in by_teacher.items():
        for d in DAYS:
            for p in PERIODS:
                model.AddAtMostOne(x[cid, sid, d, p] for cid, sid in pairs)

    # Rule 7: at most N classes may have the same subject in the same slot.
    for sid, name in problem.subjects.items():
        cap = PARALLEL_CAP.get(name)
        pairs = [(cid, s) for (cid, s) in problem.needed if s == sid]
        if cap and len(pairs) > cap:
            for d in DAYS:
                for p in PERIODS:
                    model.Add(sum(x[cid, s, d, p] for cid, s in pairs) <= cap)

    # Rule 5: saved rules.
    for sid, periods in problem.subject_not_in.items():
        for (cid, s) in problem.needed:
            if s == sid:
                for d in DAYS:
                    for p in periods:
                        model.Add(x[cid, s, d, p] == 0)
    for tid, slots in problem.unavailable.items():
        for cid, sid in by_teacher.get(tid, []):
            for d, p in slots:
                model.Add(x[cid, sid, d, p] == 0)
    for cid, sid, d, p in problem.pins:
        model.Add(x[cid, sid, d, p] == 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = min(8, os.cpu_count() or 1)
    status = solver.Solve(model)

    if status == cp_model.INFEASIBLE:
        raise ApiError(409, "infeasible", "No timetable can satisfy all the rules with the current teachers, hours and "
                                          "rules. Try removing the most recent rule or adding a teacher.")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ApiError(504, "solver_timeout", f"The solver did not find a timetable within {seconds:g} seconds. "
                                              "Try again, or remove some rules.")
    return [(cid, problem.assigned[(cid, sid)][0], sid, d, p)
            for (cid, sid, d, p), var in x.items() if solver.Value(var)]


def generate_timetable(db: sqlite3.Connection) -> dict:
    """Read the school from the database, solve, and replace all lessons. Old lessons stay if anything fails."""
    if not _busy.acquire(blocking=False):
        raise ApiError(409, "busy", "A timetable is already being generated. Wait for it to finish.")
    try:
        started = time.perf_counter()
        problem = Problem(db)
        problem.check_data()
        problem.parse_rules()
        problem.check_teacher_loads()
        lessons = solve(problem, time_limit_seconds())
        with db:  # one transaction: the old timetable is replaced only if everything above worked
            db.execute("DELETE FROM lessons")
            db.executemany("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, ?, ?)",
                           lessons)
        return {"ok": True, "lessons_count": len(lessons), "seconds": round(time.perf_counter() - started, 1)}
    finally:
        _busy.release()
