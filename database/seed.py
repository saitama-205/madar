"""Fill the database with the school's real data.

    python database/seed.py            # fill an empty database
    python database/seed.py --reset    # wipe everything (incl. lessons and rules) and re-fill

Data comes from database/seed_data.local.json (full teacher names, only on the owner's machine)
if it exists, otherwise from database/seed_data.json (shortened names, committed to GitHub).
Create both from the school's Excel with database/import_xlsb.py.
"""
import json
import sqlite3
import sys
from pathlib import Path

# Make `database.db` importable when this file is run directly (python database/seed.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection, init_db  # noqa: E402

HERE = Path(__file__).resolve().parent
PUBLIC_DATA = HERE / "seed_data.json"
LOCAL_DATA = HERE / "seed_data.local.json"

# Children first, so foreign keys never block the delete.
TABLES = ["lessons", "rules", "teacher_classes", "teachers", "subject_hours", "classes", "subjects"]


def default_data_path() -> Path:
    return LOCAL_DATA if LOCAL_DATA.exists() else PUBLIC_DATA


def is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 0


def seed(conn: sqlite3.Connection, data_path: Path | None = None, reset: bool = False) -> None:
    """Load subjects, hours, classes, teachers (with their classes) and rules. Does NOT create lessons."""
    data = json.loads((data_path or default_data_path()).read_text(encoding="utf-8"))
    with conn:  # one transaction: all or nothing
        if reset:
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO subjects (id, name, name_ar) VALUES (:id, :name, :name_ar)",
                         data["subjects"])
        conn.executemany("INSERT INTO subject_hours (grade, subject_id, per_week) VALUES (:grade, :subject, :per_week)",
                         data["subject_hours"])
        class_ids = {}
        for c in data["classes"]:
            class_ids[c["name"]] = conn.execute(
                "INSERT INTO classes (name, grade) VALUES (?, ?)", (c["name"], c["grade"])).lastrowid
        teacher_ids = []  # position in the JSON list -> database id (rules point at this position)
        for t in data["teachers"]:
            tid = conn.execute("INSERT INTO teachers (name, subject_id) VALUES (?, ?)",
                               (t["name"], t["subject"])).lastrowid
            teacher_ids.append(tid)
            conn.executemany("INSERT INTO teacher_classes (teacher_id, class_id) VALUES (?, ?)",
                             [(tid, class_ids[name]) for name in t["classes"]])
        for r in data["rules"]:
            params = {"teacher_id": teacher_ids[r["teacher_ref"]], "day": r["day"], "period": r["period"]}
            conn.execute("INSERT INTO rules (kind, params, source_text) VALUES (?, ?, ?)",
                         (r["kind"], json.dumps(params), r["source_text"]))


def seed_if_empty() -> bool:
    """Create the tables and, if the database has no subjects yet, seed it. Returns True if it seeded.

    The backend calls this on startup, so a fresh deploy (e.g. Render's temporary disk) fills itself.
    """
    conn = get_connection()
    try:
        init_db(conn)
        if is_empty(conn):
            seed(conn)
            return True
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    conn = get_connection()
    try:
        init_db(conn)
        reset = "--reset" in sys.argv
        if not reset and not is_empty(conn):
            sys.exit("Database already has data. Use --reset to wipe and re-seed.")
        seed(conn, reset=reset)
        for table in ["subjects", "classes", "teachers", "teacher_classes", "subject_hours", "rules", "lessons"]:
            print(f"{table}: {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")
    finally:
        conn.close()
