# Frontend

Owner: teammate

Plain HTML + CSS + JavaScript (ES modules), no build step. The backend serves this folder, so run the backend
(`cd backend` → `uvicorn main:app --reload`) and open http://localhost:8000.

## Pages

- `/` (`index.html`, `entry.js`): landing (moving gradient, 3D glass logo). Scrolling down, the arrow or the logo
  morph the panel into the login banner. English and Arabic (right to left), light and dark.
  **Demo sign-in: any 4-digit School ID, password `madar`.**
- `/home/` (`home/index.html`, `app/`): the app for signed-in admins, one screen per `#hash`:
  - `#timetable`: home cards, Generate, schedule by all classes, a class (grade → class) or a teacher (subject → teacher)
  - `#chat`: type a request → AI rule preview (`POST /api/rules/parse`) → Apply (save + regenerate)
  - `#rules`: data check, **Excel import** (template, upload, preview, confirm), classes, subject hours (from the
    timetable), teachers, add a teacher, rules (plain words or built by hand), Regenerate
  - `#absences`: excuse or teacher + day → ranked substitutes (`POST /api/absences`)
  - `#check`: hard-rule check, workload, gaps, hard subjects by period, lessons per class (`GET /api/analytics`), AI insights
  - `#settings`: language, dark mode, account, sign out, reset demo data

## Folders

- `app/main.js` (top bar, routing), `app/core.js` (API calls, state, icons, helpers), `app/i18n.js` (every English
  and Arabic string), `app/pages/*.js` (one file per screen). `styles.css` styles the app.
- `services/auth.js`: all sign-in goes through `MadarAuth.auth.login(schoolId, password)`. It is a mock
  (`CONFIG.MOCK_MODE`) until the backend has a login endpoint; replace `MockAuth` there.
- `services/session.js`: who is signed in, language and theme (kept in the browser).
- `assets/css/`: `fonts.css` and `theme.css` (dark mode) are shared; `base.css`, `aurora.css`, `glass.css`,
  `morph.css` style the entry page.

## Waiting on the backend

These screens call endpoints from `CONTRACT.md` that are not built yet, and say so on screen until they are:
`GET /api/import/template`, `POST /api/import`, `POST /api/import/confirm`.
Not in the contract yet (the old app had them): move/swap one lesson, edit subject hours, edit a teacher's classes,
long-term leave, remove a class.
