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
- The database is seeded **only when it is empty** (first start), never on a normal restart, so changes persist.
  To start over: `POST /api/reset` or `python database/seed.py --reset`

## Shared rules

- **Days:** `0`=Sunday, `1`=Monday, `2`=Tuesday, `3`=Wednesday, `4`=Thursday
- **Periods:** `1` to `7` (1-based)
- **Class name:** `"section/grade"`, e.g. `"2/5"` = section 2 of grade 5. Grades 1–5, sections 1–4
- All API paths start with `/api`. All requests and responses are JSON (only exceptions: the `.xlsx` template download and the `.xlsx` upload in the import endpoints)
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

The database owner (saitama-205) provides `database/schema.sql`, `database/seed.py` (fills real school data) and
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
| POST | `/api/reset` | – | `{ "ok": true }`. Wipes **all** tables (lessons, rules, added teachers/classes) and reloads the original school data from `database/seed.py` |
| GET | `/api/import/template` | – | Downloads `madar_template.xlsx` (a file, not JSON) with 3 sheets: **Classes**, **Subjects and hours**, **Teachers** (columns below) |
| POST | `/api/import` | an `.xlsx` file (multipart form field `file`) | A **preview, nothing is saved**: `{ "classes": [{ "name", "grade" }], "teachers": [{ "name", "subject", "classes": ["1/1", ..] }], "subject_hours": [{ "grade", "subject", "subject_ar", "per_week" }], "warnings": ["human sentence", ..] }` |
| POST | `/api/import/confirm` | `{ "classes", "teachers", "subject_hours" }` (the preview, edited or not; `warnings` not needed) | `{ "ok": true }`. Saves into the database and **replaces all current data** (including lessons and rules), then run Generate |
| POST | `/api/rules/parse` *(stretch)* | `{ "text": "PE never in period 7" }` | `{ "kind", "params", "explanation" }` (preview, not saved) |
| POST | `/api/absences` *(stretch)* | `{ "teacher_id", "day" }` | `[{ "day", "period", "class", "substitutes": [{ "teacher_id", "name" }] }]` |

**Lesson object:**
```json
{ "class_id": 1, "class": "1/1", "teacher_id": 4, "teacher": "Name", "subject_id": 2, "subject": "Math", "day": 0, "period": 1 }
```

**Import (.xlsx) details:**
- Template sheets and columns: **Classes** `Class` (e.g. `1/1`) · **Subjects and hours** `Subject`, `Arabic name`, `Grade 1` … `Grade 5` (lessons per week) · **Teachers** `Teacher`, `Subject`, `Classes` (comma-separated, e.g. `1/1, 2/1`).
- The preview refers to subjects and classes by **name** (nothing is saved yet, so there are no ids). Confirm checks the data again before saving; if it is invalid nothing is changed.
- A file that cannot be read (wrong type, missing sheet or column) returns `400` with error `invalid_file`. Problems in the data that do not stop the import (e.g. a teacher with no classes, a class name that does not exist) are listed in `warnings`.

## Hard rules the solver must keep

**The solver only ever reads the database.** It never reads uploaded files and never calls the AI. Imports and AI-made rules are saved into the database first (after the user has seen the preview); Generate then works only from the tables above.

1. Every class has exactly one lesson in every slot (5 × 7 = 35 per week, no free periods)
2. A teacher is never in two places at once
3. Each class gets exactly `subject_hours.per_week` lessons of each subject
4. Each lesson's teacher is the one assigned to that class for that subject
5. All saved `rules` are kept
6. **Daily cap:** a class gets at most **2** lessons of Arabic, Math, Art or Music on one day, and at most **1** of every other subject
7. **Parallel cap:** at most this many classes may have the same subject in the same slot: Science 2, Computer 2, Art 4, PE 4, Music 2 (Islamic, Arabic, English, Math, Social: no cap)

Real school data (from the school's own timetable): 10 subjects (Quran is part of Islamic Education, 4 lessons/week),
hours per week for grades 1–3 / 4–5: Islamic 4/4 · Arabic 9/7 · English 5/5 · Math 5/6 · Science 2/3 · Social 1/3 ·
Computer 1/1 · PE 4/3 · Art 2/2 · Music 2/1 (35 per class). Teachers who are "lighter" at the start or end of the day
are stored as `teacher_unavailable` rules.

## Git workflow

- `main` = always working. Nobody pushes straight to `main` after setup
- Each person works on their branch: `frontend`, `backend`, `database`
- Commit small and often. Open a pull request every 1–2 hours, and merge when it works
- Before starting new work: `git checkout main` → `git pull` → `git checkout <your-branch>` → `git merge main`
- Stay in your own folder. If you need to change something in another folder, tell its owner first
