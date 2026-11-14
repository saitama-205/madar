# Backend

Owner: saitama-205

FastAPI app. It also serves the `frontend/` folder, so the whole app runs with one command.

## Run it (Windows, first time)

```powershell
cd backend
python -m venv .venv                  # a private folder of Python packages for this project
.venv\Scripts\activate                # switch this terminal to use it (prompt shows "(.venv)")
pip install -r requirements.txt       # FastAPI, uvicorn (the web server), OR-Tools
uvicorn main:app --reload             # start; --reload restarts when you save a file
```

Open http://localhost:8000 (the frontend) or http://localhost:8000/docs (auto-generated API page where you can try every endpoint).
Next times you only need `activate` and the `uvicorn` line. macOS/Linux: `source .venv/bin/activate`.

On the first start the app creates `database/madar.db` and fills it with the school's data. After that it is **never re-seeded**, so your changes survive restarts.

To start over with the original school data (this deletes everything you added, the timetable and rules included):
- `POST /api/reset` (try it on the `/docs` page), or
- `python database/seed.py --reset` from the repo root, with the server stopped.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

Tests use a temporary database, never `database/madar.db`.

## Deploy on Render (free plan)

`render.yaml` at the repo root describes the service. Render runs `uvicorn main:app --host 0.0.0.0 --port $PORT`
(`PORT` is set by Render). The free plan's disk is temporary: the database is rebuilt from `database/seed_data.json`
on every start, so anything added through the app is lost when the service restarts.

## Code map

- `main.py`: app setup, error format (`{error, message}`), startup seeding, `POST /api/reset`, static files.
- `errors.py`: `ApiError(status, code, message)`, raise it in an endpoint to return the error format.
- `routes_school.py`: subjects, classes, teachers, timetable (read) and `POST /api/classes`, `POST /api/teachers`.
- `tests/`: pytest tests.
