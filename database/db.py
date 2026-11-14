"""Database access for Madar. The backend imports get_connection() from here."""
import os
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema.sql"


def get_db_path() -> Path:
    """database/madar.db, unless the MADAR_DB environment variable points elsewhere (used by tests)."""
    return Path(os.environ.get("MADAR_DB") or HERE / "madar.db")


def get_connection() -> sqlite3.Connection:
    """Open a connection. Rows can be read by column name: row["name"]. Foreign keys are enforced.

    Create one connection per request/operation and close it when done.
    """
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist yet (safe to call every time)."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
