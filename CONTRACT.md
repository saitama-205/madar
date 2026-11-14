# Madar – Team Contract

**Every teammate's Claude must read this file before writing code, and follow it exactly.**
If something here needs to change, agree as a team first, then update this file on `main`.

## What we're building

Madar is an AI-assisted school timetable app for an elementary school in Kuwait
(Amr bin Al-Aas Elementary: 20 classes, 10 subjects, 5 days × 7 periods).

- A **constraint solver (Google OR-Tools)** builds the timetable, so every rule is guaranteed.
- The **AI only translates** a typed request ("PE never in period 7") into a rule the solver understands.
- **Code computes the numbers, the AI only explains them.** The AI never calculates, schedules or changes data: it either translates a typed request into a rule preview, or explains metrics that Python already computed.
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
- **Class name:** `"section/grade"`, e.g. `"2/5"` = section 2 of grade 5. Grades 1–5. The school starts with sections 1–4 in every grade; a class added later gets the next free section number (the smallest unused one, so 5, 6, … once 1–4 exist). No delete endpoint: `POST /api/reset` brings back the original classes
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
| POST | `/api/classes` | `{ "grade": 3 }` | `201` `{ "id", "name", "grade", "assignments": [..], "generated": true, "violations": [..], "warnings": [..], "generation": { "ok": true, "classes": 21, "lessons_count": 735, "seconds": 9.1, "violations": ["sentence", ..], "warnings": ["sentence", ..] } }`. Creates the next free section, **assigns a teacher for every subject automatically**, then **regenerates the whole school's timetable**. See "Adding a class" below |
| GET | `/api/teachers` | – | `[{ "id", "name", "subject_id", "class_ids": [..] }]` |
| POST | `/api/teachers` | `{ "name", "subject_id", "class_ids": [..] }` | `201` the new teacher `{ "id", "name", "subject_id", "class_ids" }` **plus** `{ "generated", "violations", "warnings" }` (see "Automatic regeneration") |
| GET | `/api/timetable?class_id=ID` | – | `{ "lessons": [Lesson] }` for one class |
| GET | `/api/timetable?teacher_id=ID` | – | `{ "lessons": [Lesson] }` for one teacher |
| POST | `/api/timetable/generate` | – | `{ "ok": true, "lessons_count": 700, "seconds": 8.2, "warnings": ["sentence", ..] }` or an error explaining what's missing. A class that has no teacher for some subject is **skipped** and named in `warnings` (it gets no lessons) instead of failing the whole school; the error `missing_teachers` only happens when **no** class can be scheduled |
| GET | `/api/analytics` | – | Metrics about the saved timetable, all **computed in Python** (see "Analytics details"). `409` `no_timetable` if nothing has been generated yet |
| POST | `/api/analytics/insights` | `{ "language": "en" }` (`"en"` or `"ar"`, default `"en"`) | `{ "summary": "short paragraph", "recommendations": ["sentence", ..] }`. The backend computes the same metrics as `GET /api/analytics`, sends **only those metrics** to the AI (OpenRouter), and returns its explanation in the chosen language. `503` `ai_unavailable` if the AI key is missing or the AI is down |
| GET | `/api/rules` | – | `[{ "id", "kind", "params", "source_text" }]` |
| POST | `/api/rules` | one rule `{ "kind", "params", "source_text" }` **or** several saved together `{ "rules": [{ "kind", "params" }, ..], "source_text" }` | `201` the saved rule `{ "id", "kind", "params", "source_text" }` **plus** `{ "generated", "violations", "warnings" }` (see "Automatic regeneration"). With `rules`: `{ "rules": [saved rules, a rule that already exists is skipped], "generated", "violations", "warnings" }` |
| DELETE | `/api/rules/{id}` | – | `{ "ok": true, "generated", "violations", "warnings" }` |
| GET | `/api/settings/ai` | – | `{ "model": "openai/gpt-4o-mini", "default": "openai/gpt-4o-mini", "models": [{ "id", "label" }], "ai_configured": true }`. `model` = the model every AI call uses now; `default` = `OPENROUTER_MODEL` (or `openai/gpt-4o-mini`); `models` = the whitelist; `ai_configured` = whether `OPENROUTER_API_KEY` is set (the key itself is never returned) |
| PUT | `/api/settings/ai` | `{ "model": "google/gemini-2.0-flash-001" }` | the same object as GET. Only an id from `models` is accepted, otherwise `400` `{ "error": "invalid_model", "message" }` and nothing changes. Kept **in memory** (lost on restart, then back to `default`). There is no API key field and no custom model |
| POST | `/api/reset` | – | `{ "ok": true }`. Wipes **all** tables (lessons, rules, added teachers/classes) and reloads the original school data from `database/seed.py` |
| GET | `/api/import/template` | – | Downloads `madar_template.xlsx` (a file, not JSON): **one sheet** named `Timetable data` with the columns `class`, `subject`, `teacher`, `hours_per_week` (one row per class + subject) |
| POST | `/api/import` | an `.xlsx` file (multipart form field `file`) | A **preview, nothing is saved**: `{ "rows": [{ "class": "1/1", "subject": "Math", "teacher": "Sara M.", "hours_per_week": 5 }], "warnings": ["human sentence", ..] }` |
| POST | `/api/import/confirm` | `{ "rows": [{ "class", "subject", "teacher", "hours_per_week" }] }` (the preview, edited or not; `warnings` not needed) | `{ "ok": true, "generated", "violations", "warnings" }`. Saves into the database and **replaces all current data** (including lessons and rules), then regenerates |
| POST | `/api/rules/parse` *(stretch)* | `{ "text": "PE never in period 7" }` | `{ "kind", "params", "rules": [{ "kind", "params" }], "explanation" }` (preview, not saved; a swap also has `"swap"`, see AI endpoints details) |
| POST | `/api/absences` *(stretch)* | `{ "teacher_id", "mode": "short"\|"long", "day": 0-4, "days": [0-4, ..], "lang": "en"\|"ar" }` (`mode` default `"short"`; short needs `day` or `days`) | short: `[{ "day", "period", "class", "substitutes": [{ "teacher_id", "name" }] }]` (flat list, ordered by day then period). long: `{ "mode": "long", "teacher_id", "teacher", "assignments": [{ "class_id", "class", "subject_id", "subject", "subject_ar", "per_week", "lessons": [{ "day", "period" }], "substitutes": [{ "teacher_id", "name", "reason", "load", "load_after", "capacity", "over_capacity", "clashes" }] }], "warnings": [..] }`. Nothing is saved |
| POST | `/api/absences/apply` | `{ "teacher_id", "assignments": [{ "class_id", "substitute_id" }] }` | `{ "ok": true, "reassigned": [{ "class_id", "class", "subject_id", "subject", "from_teacher_id", "to_teacher_id", "to_teacher" }], "generated", "violations", "warnings" }`. Long-term absence: reassigns, then regenerates (see "Absences") |
| GET | `/api/subject-hours` | – | `[{ "grade", "subject_id", "per_week" }]` |
| PUT | `/api/subject-hours/{grade}` | `{ "hours": { "<subject_id>": n, .. } }` | `{ "grade", "hours": { "<subject_id>": n, .. }, "generated", "violations", "warnings" }`. See "Subject hours" |

**Lesson object:**
```json
{ "class_id": 1, "class": "1/1", "teacher_id": 4, "teacher": "Name", "subject_id": 2, "subject": "Math", "day": 0, "period": 1 }
```

**Analytics details** (`GET /api/analytics` response; days are Sunday to Thursday = 5 numbers, periods 1 to 7 = 7 numbers):
```json
{
  "teacher_load": [{ "teacher_id": 4, "teacher": "Name", "subject": "Math", "per_week": 16, "per_day": [4, 3, 3, 3, 3] }],
  "teacher_gaps": [{ "teacher_id": 4, "teacher": "Name", "day": 0, "gap_periods": 2 }],
  "hard_subjects_by_period": { "Arabic": [..7..], "English": [..7..], "Math": [..7..], "Science": [..7..] },
  "class_load": [{ "class_id": 1, "class": "1/1", "per_day": [7, 7, 7, 7, 7] }],
  "rule_check": { "ok": true, "violations": ["human sentence", ..] }
}
```
- `teacher_load`: lessons per teacher per week and per day.
- `teacher_gaps`: free periods **between** a teacher's first and last lesson on a day (only days with a gap are listed).
- `hard_subjects_by_period`: how many lessons of each hard subject (Arabic, English, Math, Science) fall in each period, across the whole school.
- `class_load`: lessons per class per day (7 per day when the timetable is complete).
- `rule_check`: Python re-checks the hard rules below against the saved lessons. `ok` is `false` and `violations` is filled if any rule is broken.
- `unscheduled_classes`: names of classes that have no lessons at all (just added, or skipped by Generate). They are listed here, not as `rule_check` violations. Example response key: `"unscheduled_classes": ["5/1"]`.
- **The AI rule:** for `/api/analytics/insights` the AI receives only these metrics. Every number in its answer must come from them: the AI explains and suggests, it never calculates, and its recommendations are text only (nothing is changed automatically). The key is `OPENROUTER_API_KEY` in `.env` (and Render's environment), never in the code or on GitHub.

**Adding a class** (`POST /api/classes`) does everything in this order: (1) create the class (its lessons per subject come from the grade's `subject_hours`, nothing extra to create); (2) assign **one teacher per subject** the grade has lessons in; (3) run Generate for the whole school (same code as `POST /api/timetable/generate`, can take several seconds).

- **Who is assigned:** teachers of that subject. Preferred: teachers who already teach that subject in the same grade; otherwise any teacher of the subject. Among them the one with the lowest weekly load that still has room: a teacher's limit is the solver's own, **35 minus the slots they are unavailable** (`teacher_unavailable` rules). If nobody has room, the least loaded teacher of that subject is chosen and flagged `over_capacity: true` (Generate will then refuse with `teacher_overloaded` naming the teacher). If the school has no teacher of that subject, `teacher_id` is `null` and the class is skipped by Generate with a warning.
- **`assignments`** (one per subject): `{ "subject_id", "subject", "per_week", "teacher_id", "teacher", "load_after", "capacity", "over_capacity", "same_grade" }`.
- **`generation`**: `classes` = number of classes that now have lessons; `violations` = the hard-rule re-check from `GET /api/analytics`; `warnings` = e.g. skipped classes.
- **The class and its teacher assignments are always kept.** If generation fails, the old timetable is left untouched and the response is the normal `{ "error", "message" }` with the generator's status and code (`teacher_overloaded` 422, `infeasible` 409, `busy` 409, `solver_timeout` 504, or `generation_failed` 500). The message starts "Class 5/3 was added and its teachers were assigned, but the timetable could not be generated: ..." and ends "The previous timetable was kept." The frontend should then reload `GET /api/classes` and `GET /api/teachers`.

**AI model setting** (`GET/PUT /api/settings/ai`): the whitelist is `openai/gpt-4o-mini` (GPT-4o mini), `google/gemini-2.0-flash-001` (Gemini 2.0 Flash) and `anthropic/claude-3.5-haiku` (Claude 3.5 Haiku). The chosen model is used by every AI call (rule parsing, absence explanations, analytics insights). The server's `OPENROUTER_MODEL` is only the starting model; the key stays in `.env`/Render and can never be set through the API.

**AI endpoints details** (all use OpenRouter; `OPENROUTER_API_KEY` in `.env`/Render, optional `OPENROUTER_MODEL`, default `openai/gpt-4o-mini`; only shortened teacher names are ever sent to the AI):
- `POST /api/rules/parse`: one request per call (a swap is one request that saves two pins). **Response:** `{ "kind", "params", "rules": [{ "kind", "params" }, ..], "explanation" }`; `rules` is what Confirm saves (one rule, or two for a swap) with `POST /api/rules` `{ "rules": rules }`; `kind`/`params` repeat the first rule for older clients. **Swap two lessons** (e.g. "swap class 1/1 Sunday period 1 with Tuesday period 3", English or Arabic): both slots must have a lesson in the saved timetable and be different subjects; the preview is two `pin_lesson` rules (each lesson pinned at the other's slot) and the response also has `"swap": { "class_id", "a": { "day", "period", "subject_id" }, "b": { .. } }` (the slots before the swap). The swap is first tried on the saved timetable and **rejected with `422` `swap_breaks_rule`** (message: "This swap is not allowed because it would break a rule: ...") if it would add any hard-rule violation: a teacher in two places, a teacher unavailable, a subject banned from that period, the daily or parallel cap, or an existing pinned lesson; `409` `no_timetable`, `422` `cannot_parse` for the usual reasons (no lesson in a slot, same slot, unknown class/day/period). Nothing is changed by the preview. Class, subject, day and the kind are matched case-insensitively. Other kinds below. One rule per request. Rule kinds it understands: `subject_not_in_period`, `teacher_unavailable`, `pin_lesson`, and "move a lesson" (e.g. "Move class 1/1 Sunday period 1 to Monday period 1"). A move is previewed as a `pin_lesson` for the same subject at the target slot (the subject is read from the saved timetable; `409` `no_timetable` if there is none, `cannot_parse` if the class has no lesson at the source slot). No new rule kind is stored. `422` `cannot_parse` (the request does not fit one rule kind, or a name/subject/class/day/period is not recognised), `503` `ai_unavailable` (no key or the AI is down). Preview only; the `explanation` is written by the backend from the validated params.
- `POST /api/absences` (mode `"short"`; for `"long"` see "Absences"): no AI is needed for the result. `day` is `0`–`4`; optional **`lang`** (`"en"` or `"ar"`, default `"en"`) = the UI language; the `explanation` sentence (AI, or the built-in template when there is no AI key or the AI fails) is written in it. The older name `language` is still accepted, `lang` wins if both are sent. `404` unknown teacher, `409` `no_timetable`. Besides the contract fields each item also has `class_id`, `subject`, `subject_ar`, `explanation` (one sentence about the top substitute, `null` if there is none) and `explanation_source` (`"ai"` or `"template"`); each substitute also has `reason` (`same_subject_free` / `free_only`) and `day_load`. Ranking: same subject first, then fewest lessons that day; teachers with a lesson or a `teacher_unavailable` rule in that slot are left out; at most 3 per lesson.
- `POST /api/analytics/insights`: `502` `ai_bad_answer` if the AI's answer contains a number that is not in the metrics (it is discarded).

**Automatic regeneration** (every endpoint that changes data: `POST /api/rules`, `DELETE /api/rules/{id}`, `PUT /api/subject-hours/{grade}`, `POST /api/classes`, `POST /api/teachers`, `POST /api/absences/apply`, `POST /api/import/confirm`):
- The change is saved, then the whole school's timetable is regenerated (same code as `POST /api/timetable/generate`; can take several seconds). The response contains these three fields (merged into the endpoint's own response, see the table):
  - `generated` (boolean): `true` if a new timetable was built and saved.
  - `violations` (list of sentences): the hard-rule re-check of the timetable that is saved **now** (the same sentences as `GET /api/analytics` `rule_check.violations`; `[]` if there is no timetable).
  - `warnings` (list of sentences): from the generator (e.g. skipped classes). When `generated` is `false` the first warning is the reason followed by "The previous timetable was kept.", and the response also has `error` (`infeasible`, `teacher_overloaded`, `bad_hours`, `busy`, `solver_timeout`, `generation_failed`, ...). Optional extras when `generated` is `true`: `lessons_count`, `seconds`.
- **A failed solve never wipes the timetable** and never fails the request: the old lessons stay exactly as they were and the data change that was just saved is kept (the status is `200`/`201`, `generated` is `false`). Exception: `POST /api/classes` keeps its older behaviour of returning the generator's error (see "Adding a class"). `POST /api/import/confirm` replaces all data including lessons by design, so after it a failed solve leaves no timetable.
- If another Generate is already running, `generated` is `false` with `error` `busy`.

**Subject hours** (`PUT /api/subject-hours/{grade}`, grade 1 to 5): `hours` maps a subject id (as a string key) to lessons per week; subjects you leave out keep their current hours. After applying the change the grade's total must be exactly **35**, every value a whole number 0 to 35 and every key an existing subject; otherwise `400` `{ "error": "invalid_hours", "message": "..." }` and nothing is changed. Then it regenerates (see above).

**Absences** (`POST /api/absences`):
- `mode` `"short"` (default): suggestions only. `day` (one day) or `days` (a list, no duplicates needed); the result is one flat list ordered by day, then period. Each item has the fields described under AI endpoints details. Without `day`/`days` it is `422` `invalid_request`.
- `mode` `"long"`: lists every class the absent teacher teaches, each with ranked `substitutes`. A class has exactly one teacher per subject and a teacher teaches one subject, so only teachers of the **same subject** can take over (`reason` is `"same_subject"`; if there is none, `substitutes` is `[]` and `warnings` says so). Ranking, best first: has room (`over_capacity` false), fewer `clashes` (lessons of the class's current slots where the candidate already teaches or is unavailable), lower `load` (lessons per week now), lower id. `load_after` = `load` + this class's weekly hours; `capacity` = 35 minus the candidate's unavailable slots. At most 5 per class. Nothing is saved.
- `POST /api/absences/apply` (after the user confirms): each `{ "class_id", "substitute_id" }` makes the substitute that class's teacher for the absent teacher's subject (the absent teacher stays in the database, just without those classes), then it regenerates. Errors (nothing is changed): `404` `not_found` (unknown teacher, substitute, or the absent teacher does not teach that class), `422` `invalid_substitute` (a different subject, or the absent teacher themselves), `422` `invalid_request` (empty list or a class twice), `409` `substitute_over_capacity` (the substitute would exceed their weekly limit, counting all assignments in the request). If the solve fails the reassignment is kept and the old timetable stays (`generated` false).

**Import (.xlsx) details:**
- **One sheet**, named `Timetable data`, header row `class`, `subject`, `teacher`, `hours_per_week`, **one row per class + subject**. Columns are matched ignoring case and order. (A workbook with a single sheet of another name is accepted too.) Classes, subjects, each grade's hours per week and the teachers with their classes are all derived from the rows.
- `GET /api/import/template` is pre-filled with the school's current setup: a row for every class and each subject the class has lessons in, with the teacher's (already shortened) name and the hours.
- `POST /api/import` (multipart form field `file`, **.xlsx only**, max 5 MB) returns the preview `{ "rows": [{ "class", "subject", "teacher", "hours_per_week" }], "warnings": [..] }` and **saves nothing**. `class` is `"section/grade"`, `subject` is the English name (an Arabic name or known alias of an existing subject is turned into the English name), `teacher` is the shortened name (`""` if the cell is empty), `hours_per_week` a whole number 0 to 35.
- **`400` `invalid_file`** (always `{ "error", "message" }`, the message says what is wrong): no file, not `.xlsx`, not a real Excel file, empty file, over 5 MB, the sheet or a column is missing (the message names it), no data rows, no valid rows, or an `hours_per_week` cell that is not a whole number 0 to 35 (the message gives the row).
- **`warnings`** (human sentences, never errors): a row with an invalid class name, an empty subject, or a duplicate class + subject (the row is ignored); two different teachers of one subject shortened to the same name (the second is saved as `"Sara M. (2)"`); a class whose hours do not add up to 35; classes of one grade that disagree on a subject's hours (Confirm refuses this); a class + subject with hours but no teacher (Generate will skip that class).
- **Only shortened teacher names are used.** Whatever is typed in `teacher` is shortened to first name + initial (`"Sara Khaled Mutairi"` becomes `"Sara M."`) in the preview, and again on confirm, so full names are never stored, returned or sent to the AI. The same shortened name on several rows (same subject) is one teacher.
- `POST /api/import/confirm` takes `{ "rows": [{ "class", "subject", "teacher", "hours_per_week" }] }` (the preview; `warnings` may be sent back and is ignored), checks everything again and, only if valid, **replaces all current data in one transaction** (classes, subjects, hours, teachers and assignments, **and** lessons and rules; ids are new), then regenerates. Response `{ "ok": true, "generated", "violations", "warnings" }`. A subject that already exists keeps its Arabic name; a grade that has no class in the file gets 0 hours for every subject. If anything is wrong it returns `422` `invalid_import` (or `invalid_request` for a malformed body) and **nothing is changed**: an invalid or out-of-range class, an empty subject, hours outside 0 to 35, two rows for one class + subject, or different hours for one subject in classes of the same grade.

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
