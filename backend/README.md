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
- `routes_timetable.py`: `POST /api/timetable/generate`.
- `solver.py`: the OR-Tools solver. Reads the database only, checks the data first (missing teachers, hours not 35,
  overloaded teachers, broken rules) with clear errors, solves in about a second, and replaces `lessons` in one
  transaction, so a failed run keeps the old timetable. The daily and parallel caps live at the top of this file.
  Set `MADAR_SOLVER_SECONDS` to change the 30 second time limit.
- `routes_rules.py`: `GET`, `POST`, `DELETE /api/rules`. A saved rule is used the next time Generate runs.
- `rule_params.py`: the settings each rule kind needs (whole numbers, day 0-4, period 1-7, no unknown keys).
  Shared by the rules endpoints and the solver, so they always agree on what a valid rule is.
- `tests/`: pytest tests. `test_solver.py` re-checks every contract hard rule on the saved lessons.

## AI privacy rule

Any AI feature (OpenRouter) may only receive shortened teacher names as stored in the database (first name + initial, e.g. `Sara K.`), never full names, and no other personal data. The full-name file `database/seed_data.local.json` and `source data/` stay on the owner's machine (git-ignored).
