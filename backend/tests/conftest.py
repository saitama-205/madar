import sys
from pathlib import Path

import pytest

# Make `database` importable (it lives next to backend/, at the repo root).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def no_background_generation(monkeypatch):
    """Starting the app must not launch the startup solver thread in tests: it would keep the global "one
    generation at a time" lock busy and make unrelated tests fail with 409 busy. The startup test turns it on itself."""
    monkeypatch.setenv("MADAR_AUTO_GENERATE", "0")


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


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """The real app (starts and seeds like production) on a temp database, plus a direct DB connection."""
    monkeypatch.setenv("MADAR_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("MADAR_AUTO_GENERATE", "0")  # tests control when the solver runs
    from fastapi.testclient import TestClient

    from database.db import get_connection
    from main import create_app

    with TestClient(create_app(frontend_dir=tmp_path / "no-frontend")) as client:
        client.db = get_connection()
        yield client
        client.db.close()
