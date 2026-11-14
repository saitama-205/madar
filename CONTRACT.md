# Madar – Team Contract

**Every teammate's Claude must read this file before writing code, and follow it exactly.**
If something here needs to change, agree as a team first, then update this file on `main`.

## What we're building

Madar is an AI-assisted school timetable app for an elementary school in Kuwait
(Amr bin Al-Aas Elementary: 20 classes, 10 subjects, 5 days × 7 periods).

- A **constraint solver (Google OR-Tools)** builds the timetable, so every rule is guaranteed.
- The **AI only translates** a typed request ("PE never in period 7") into a rule the solver understands.
- The user always sees a preview before anything changes.

### Demo goal (must work by the end)

1. See the timetable for one class or one teacher
2. Press **Generate** and the solver builds a valid timetable
3. Add a teacher, class or rule, then regenerate
4. *(Stretch)* Type a rule in plain English/Arabic → AI turns it into a rule → preview → save
5. *(Stretch)* Mark a teacher absent → get suggested substitutes

## Tech stack

| Part | Tech | Owner | Folder |
| --- | --- | --- | --- |
| Frontend | Plain HTML + CSS + JavaScript (`fetch` calls to the API). No build step | frontend teammate | `frontend/` |
| Backend | Python 3.12+, **FastAPI**, **OR-Tools**, uvicorn | saitama-205 | `backend/` |
| Database | **SQLite** (one file: `database/madar.db`) + schema + seed data | saitama-205 | `database/` |

- The backend serves the frontend files too, so the whole app runs with **one command**.
- Run: `cd backend` → `pip install -r requirements.txt` → `uvicorn main:app --reload` → open http://localhost:8000
- API docs auto-generated at http://localhost:8000/docs

## Shared rules

- **Days:** `0`=Sunday, `1`=Monday, `2`=Tuesday, `3`=Wednesday, `4`=Thursday
- **Periods:** `1` to `7` (1-based)
- **Class name:** `"section/grade"`, e.g. `"2/5"` = section 2 of grade 5. Grades 1–5, sections 1–4
- All API paths start with `/api`. All requests and responses are JSON
- Errors return `{ "error": "short_code", "message": "human sentence" }` with a 4xx/5xx status
- Secrets (AI key) go in `.env`, never in the code or on GitHub

## Database tables (SQLite)

| Table | Columns |
| --- | --- |
| `subjects` | `id` INTEGER PK, `name` TEXT UNIQUE, `name_ar` TEXT |
| `subject_hours` | `grade` INTEGER, `subject_id` INTEGER → subjects, `per_week` INTEGER. PK (`grade`, `subject_id`) |
| `classes` | `id` INTEGER PK, `name` TEXT UNIQUE (e.g. `"2/5"`), `grade` INTEGER |
| `teachers` | `id` INTEGER PK, `name` TEXT, `subject_id` INTEGER → subjects |
| `teacher_classes` | `teacher_id` → teachers, `class_id` → classes. PK (both) |
| `lessons` | `id` INTEGER PK, `class_id`, `teacher_id`, `subject_id`, `day` INTEGER 0–4, `period` INTEGER 1–7 |
| `rules` | `id` INTEGER PK, `kind` TEXT, `params` TEXT (JSON), `source_text` TEXT |

Rule kinds: `subject_not_in_period` `{subject_id, period}` · `teacher_unavailable` `{teacher_id, day, period}` · `pin_lesson` `{class_id, subject_id, day, period}`

The database teammate provides `database/schema.sql`, `database/seed.py` (fills real school data) and
`database/db.py` with a `get_connection()` function the backend imports.

## API endpoints

| Method | Path | Request body | Response |
| --- | --- | --- | --- |
| GET | `/api/health` | – | `{ "ok": true }` |
| GET | `/api/subjects` | – | `[{ "id", "name", "name_ar" }]` |
| GET | `/api/classes` | – | `[{ "id", "name", "grade" }]` |
| POST | `/api/classes` | `{ "grade": 3 }` | the new class (next free section) |
| GET | `/api/teachers` | – | `[{ "id", "name", "subject_id", "class_ids": [..] }]` |
| POST | `/api/teachers` | `{ "name", "subject_id", "class_ids": [..] }` | the new teacher |
| GET | `/api/timetable?class_id=ID` | – | `{ "lessons": [Lesson] }` for one class |
| GET | `/api/timetable?teacher_id=ID` | – | `{ "lessons": [Lesson] }` for one teacher |
| POST | `/api/timetable/generate` | – | `{ "ok": true, "lessons_count": 700, "seconds": 8.2 }` or an error explaining what's missing |
| GET | `/api/rules` | – | `[{ "id", "kind", "params", "source_text" }]` |
| POST | `/api/rules` | `{ "kind", "params", "source_text" }` | the saved rule |
| DELETE | `/api/rules/{id}` | – | `{ "ok": true }` |
| POST | `/api/rules/parse` *(stretch)* | `{ "text": "PE never in period 7" }` | `{ "kind", "params", "explanation" }` (preview, not saved) |
| POST | `/api/absences` *(stretch)* | `{ "teacher_id", "day" }` | `[{ "day", "period", "class", "substitutes": [{ "teacher_id", "name" }] }]` |

**Lesson object:**
```json
{ "class_id": 1, "class": "1/1", "teacher_id": 4, "teacher": "Name", "subject_id": 2, "subject": "Math", "day": 0, "period": 1 }
```

## Hard rules the solver must keep

1. Every class has exactly one lesson in every slot (5 × 7 = 35 per week, no free periods)
2. A teacher is never in two places at once
3. Each class gets exactly `subject_hours.per_week` lessons of each subject
4. Each lesson's teacher is the one assigned to that class for that subject
5. All saved `rules` are kept

## Git workflow

- `main` = always working. Nobody pushes straight to `main` after setup
- Each person works on their branch: `frontend`, `backend`, `database`
- Commit small and often. Open a pull request every 1–2 hours, and merge when it works
- Before starting new work: `git checkout main` → `git pull` → `git checkout <your-branch>` → `git merge main`
- Stay in your own folder. If you need to change something in another folder, tell its owner first
