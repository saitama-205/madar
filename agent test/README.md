# Agent test: the Madar Scheduler (AI agent)

A snapshot of the AI agent for the team to try and review. **It is not wired into the app on `main`**: nothing in
`backend/` or `frontend/` uses these files yet. It was built on commit `d3fefe6`, before the frontend moved to
`frontend/app/` (commit `071d781`).

## What it does

The **Scheduler** tab takes a request in English or Arabic, for example *"Aisha A. has left the school. Huda A. will take
her classes"*, *"Class 2/3 has no teacher on Monday, period 3. Who can cover?"* or *"PE should never be in period 7"*.
The AI works in steps with tools (at most 8 rounds) and ends with a short answer and numbered **proposals** (P1, P2...)
that the admin **approves or rejects**.

| Tool | What it does |
| --- | --- |
| `find_teachers` | Teachers by part of a name (Arabic or English) and/or subject |
| `get_timetable` | The week of one class or one teacher |
| `list_rules` | Saved rules, optionally for one teacher |
| `find_cover` | An absent teacher's lessons on a day, with ranked substitutes (uses `substitutes.find_affected`) |
| `get_slot` | What is taught in one day + period, or in one class at that time |
| `who_is_free` | Teachers free in one day + period, same subject first, then the lightest day |
| `propose_rule` | A rule for the admin to approve (validated like `POST /api/rules`) |
| `propose_new_teacher` | A teacher who takes over one subject in given classes (like `POST /api/teachers`) |

**Safety (matches CONTRACT.md)**
- The agent **never writes to the database**. A proposal is a ready request body for an existing endpoint
  (`POST /api/rules` or `POST /api/teachers`); the app sends it only when the admin presses Approve, then Generate.
- Proposals are validated by the same code as those endpoints (`rule_params.parse_params`, `check_things_exist`).
  Their description and impact (lessons that move, teacher load, "Generate will fail") are computed by Python.
- Only shortened teacher names reach the AI (`ai.privacy.short_name`, plus a final filter on everything sent).
- Key: `OPENROUTER_API_KEY` in the repo's `.env` (optional `OPENROUTER_MODEL`, default `openai/gpt-4o-mini`; the model
  must support tool calling). The key never reaches the browser.

**English names.** `database/teacher_names_en.json` gives every teacher an English spelling (`فاطمة ج.` → `Fatima J.`),
used by the agent and by the name autocomplete (typing `Fa` completes *Fatima J.*, typing `فا` completes *فاطمة ج.*).
Spellings are common Kuwaiti forms; initials follow one letter per Arabic letter (ش Sh, خ Kh, غ Gh, ذ/ض Dh, ع A, ق Q, إ E).
**Please check them against school records.** Two Arabic names look like typos in the source data: `األطاف` (probably
`ألطاف`, Altaf) and `حنبن` (probably `حنين`, Haneen).

## Try it without installing anything

Download **`preview.html`** and open it in a browser. It is the app (Timetable, Data, Rules, Scheduler tabs) running
on the school's sample data, with the backend simulated in the browser: a simple scheduler stands in for OR-Tools, and
the Scheduler's replies are simulated (no OpenRouter key). Press Generate first.

## Files

| Path here | Goes to | Note |
| --- | --- | --- |
| `backend/ai/agent.py` | `backend/ai/agent.py` | The agent: tools, loop, privacy filter |
| `backend/routes_agent.py` | `backend/routes_agent.py` | `POST /api/agent` |
| `backend/names_en.py` | `backend/names_en.py` | English name lookup |
| `backend/tests/test_agent.py` | `backend/tests/test_agent.py` | 16 tests with a scripted fake model (no network) |
| `database/teacher_names_en.json` | `database/teacher_names_en.json` | English names, keyed by the stored Arabic name |
| `frontend-scheduler-tab/` | (port it) | The Scheduler tab in the **old** single `app.js` layout |
| `madar_agent.patch` | | Every change above as one git patch against `d3fefe6` |
| `preview.html` | | The browser preview described above |

## Wiring it into today's `main`

The backend helpers the agent uses (`substitutes.find_affected`, `ai.rule_parser.explain`, `routes_rules.check_things_exist`,
`rule_params.parse_params`, `ai.llm`, `ai.normalize`, `ai.privacy`) still have compatible signatures on `main`.

1. Copy the five backend/database files above to the same paths.
2. `backend/main.py`: add the import with the other routers, and register it:
   ```python
   from routes_agent import router as agent_router  # noqa: E402
   ...
   app.include_router(agent_router)  # AI scheduler (proposals only, never saves)
   ```
3. `backend/routes_school.py`: add `from names_en import english_name`, and in `teachers_with_classes` return
   `{**dict(r), "name_en": english_name(r["name"]), "class_ids": links.get(r["id"], [])}`.
4. `CONTRACT.md`: `GET /api/teachers` gains `name_en`; add `POST /api/agent` (shapes below).
5. Run `cd backend && python -m pytest -q`.
6. Frontend: `main` now has its own chat ("Ask Madar") and teacher autocomplete in `frontend/app/`. Port the Scheduler
   from `frontend-scheduler-tab/app.js` (functions `renderScheduler`, `drawChat`, `proposalCard`, `decide`,
   `sendToScheduler`, `suggestTeachers`, `attachNameSuggestions`) or point the existing chat at `POST /api/agent`.

## API

`POST /api/agent` with `{ "message", "language": "en"|"ar", "history": [{ "role": "user"|"assistant", "content" }] }` returns
`{ "reply", "proposals": [{ "id", "type": "rule"|"teacher", "description", "impact": [{ "level", "text" }],
"request": { "method", "path", "body" } }], "steps": [{ "tool", "summary" }] }`. Nothing is saved.
`503 ai_unavailable` when there is no key or the AI fails before doing anything.
