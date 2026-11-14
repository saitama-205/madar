import json
import re
import sqlite3

import pytest

from database.seed import PUBLIC_DATA, seed, seed_if_empty

TABLES = {"subjects", "subject_hours", "classes", "teachers", "teacher_classes", "lessons", "rules"}


def count(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_schema_has_the_seven_contract_tables(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_seed_loads_the_real_school(seeded):
    assert count(seeded, "SELECT COUNT(*) FROM subjects") == 10
    assert count(seeded, "SELECT COUNT(*) FROM classes") == 20
    assert count(seeded, "SELECT COUNT(*) FROM teachers") == 79
    assert count(seeded, "SELECT COUNT(*) FROM lessons") == 0  # lessons come from the solver, not the seed
    names = {r["name"] for r in seeded.execute("SELECT name FROM classes")}
    assert names == {f"{s}/{g}" for g in range(1, 6) for s in range(1, 5)}


def test_every_grade_has_35_lessons_per_week(seeded):
    rows = seeded.execute("SELECT grade, SUM(per_week) AS total FROM subject_hours GROUP BY grade").fetchall()
    assert len(rows) == 5
    assert all(r["total"] == 35 for r in rows)


def test_real_timetable_hours(seeded):
    def hours(subject, grade):
        return count(seeded, """SELECT per_week FROM subject_hours h JOIN subjects s ON s.id = h.subject_id
                                WHERE s.name = ? AND h.grade = ?""", subject, grade)
    assert (hours("Arabic", 1), hours("Arabic", 5)) == (9, 7)
    assert (hours("English", 1), hours("English", 5)) == (5, 5)
    assert (hours("Math", 3), hours("Math", 4)) == (5, 6)


def test_every_class_and_subject_has_exactly_one_teacher(seeded):
    """Contract hard rule 4 needs exactly one assigned teacher per class and subject."""
    rows = seeded.execute("""
        SELECT tc.class_id, t.subject_id, COUNT(*) AS n
        FROM teacher_classes tc JOIN teachers t ON t.id = tc.teacher_id
        GROUP BY tc.class_id, t.subject_id""").fetchall()
    assert len(rows) == 20 * 10
    assert all(r["n"] == 1 for r in rows)


def test_no_teacher_is_overloaded(seeded):
    """A teacher's weekly lessons (classes x hours) must fit in the 35 slots."""
    rows = seeded.execute("""
        SELECT t.id, SUM(h.per_week) AS load
        FROM teachers t
        JOIN teacher_classes tc ON tc.teacher_id = t.id
        JOIN classes c ON c.id = tc.class_id
        JOIN subject_hours h ON h.grade = c.grade AND h.subject_id = t.subject_id
        GROUP BY t.id""").fetchall()
    assert len(rows) == 79
    assert max(r["load"] for r in rows) <= 18  # the school's real maximum


def test_lighter_teacher_rules_are_valid_json_rules(seeded):
    rules = seeded.execute("SELECT * FROM rules").fetchall()
    assert len(rules) == 80
    teacher_ids = {r["id"] for r in seeded.execute("SELECT id FROM teachers")}
    for r in rules:
        p = json.loads(r["params"])
        assert r["kind"] == "teacher_unavailable"
        assert p["teacher_id"] in teacher_ids and 0 <= p["day"] <= 4 and 1 <= p["period"] <= 7


def test_seed_if_empty_only_seeds_once(tmp_path, monkeypatch):
    monkeypatch.setenv("MADAR_DB", str(tmp_path / "once.db"))
    assert seed_if_empty() is True
    assert seed_if_empty() is False


def test_reset_replaces_everything(seeded):
    seeded.execute("INSERT INTO rules (kind, params, source_text) VALUES ('x', '{}', 'extra')")
    seeded.commit()
    seed(seeded, data_path=PUBLIC_DATA, reset=True)
    assert count(seeded, "SELECT COUNT(*) FROM rules") == 80
    assert count(seeded, "SELECT COUNT(*) FROM teachers") == 79


def test_database_blocks_double_booking(seeded):
    """The UNIQUE constraints are a safety net for hard rules 1 and 2."""
    cls = seeded.execute("SELECT class_id, teacher_id FROM teacher_classes LIMIT 1").fetchone()
    other = seeded.execute("SELECT id FROM classes WHERE id != ? LIMIT 1", (cls["class_id"],)).fetchone()
    subject = seeded.execute("SELECT subject_id FROM teachers WHERE id = ?", (cls["teacher_id"],)).fetchone()[0]
    insert = "INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, 0, 1)"
    seeded.execute(insert, (cls["class_id"], cls["teacher_id"], subject))
    with pytest.raises(sqlite3.IntegrityError):  # same teacher, same slot, other class
        seeded.execute(insert, (other["id"], cls["teacher_id"], subject))


def test_bad_day_is_rejected(seeded):
    cls = seeded.execute("SELECT class_id, teacher_id FROM teacher_classes LIMIT 1").fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, 1, 5, 1)",
                       (cls["class_id"], cls["teacher_id"]))


def test_public_seed_file_has_only_shortened_names():
    """Guard: the committed file must never contain full teacher names."""
    data = json.loads(PUBLIC_DATA.read_text(encoding="utf-8"))
    for t in data["teachers"]:
        assert re.fullmatch(r"\S+( \S\.)?( \(\d+\))?", t["name"]), t["name"]
