# Frontend

Owner: teammate

Plain HTML + CSS + JavaScript, no build step. The backend serves this folder, so run the backend
(`cd backend` → `uvicorn main:app --reload`) and open http://localhost:8000.

## Pages

- `/` (`index.html`, `entry.js`): landing (animated gradient, 3D glass logo) then scroll down to sign in.
  English and Arabic (right to left). **Demo sign-in: any 4-digit School ID, password `madar`.**
- `/home/` (`home/index.html`, `app.js`, `styles.css`): the timetable app (Timetable, Data, Rules).
  Only for signed-in admins; anyone else is sent back to the sign-in.

## Folders

- `services/auth.js`: all sign-in goes through `MadarAuth.auth.login(schoolId, password)`. It is a mock
  (`CONFIG.MOCK_MODE`) until the backend has a login endpoint; replace `MockAuth` with a real one there.
- `services/session.js`: who is signed in and the chosen language (kept in the browser).
- `assets/css/`: `fonts.css` (shared), `base.css`, `aurora.css`, `glass.css`, `scroll.css` (entry page).
- `assets/fonts/`: Cascadia Code and IBM Plex Sans Arabic. `assets/*.png`: logo and wordmark.
