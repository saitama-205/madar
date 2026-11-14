import sys
from pathlib import Path

import pytest

# Make `database` importable (it lives next to backend/, at the repo root).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """An empty database in a temp folder (never touches database/madar.db)."""
    monkeypatch.setenv("MADAR_DB", str(tmp_path / "test.db"))
    from database.db import get_connection, init_db

    c = get_connection()
    init_db(c)
    yield c
    c.close()


@pytest.fixture()
def seeded(conn):
    """The temp database filled from the committed seed_data.json (shortened names)."""
    from database.seed import PUBLIC_DATA, seed

    seed(conn, data_path=PUBLIC_DATA)
    return conn
