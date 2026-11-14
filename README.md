# Madar

AI-assisted school timetable app for an elementary school in Kuwait (Amr bin Al-Aas Elementary: 20 classes,
10 subjects, 5 days x 7 periods). Built for a hackathon.

**Live demo:** https://madar-qaom.onrender.com
Sign in with **any 4-digit School ID** and the password **`madar`**.
(Free hosting: the first load can take about a minute to wake up, and anything you change is reset when the service restarts.)

## The idea: the AI proposes, the solver proves

- A **constraint solver (Google OR-Tools)** builds the timetable, so every hard rule is guaranteed, not hoped for.
- The **AI only translates and explains**. It turns a typed request ("swap class 1/1 Sunday period 1 with Tuesday
  period 3", in English or Arabic) into a rule, and it words explanations of numbers that Python already computed.
  It never schedules, calculates or changes data.
- You always see a **preview and press Confirm** before anything changes. After a change the timetable is rebuilt
  automatically, and a failed rebuild never wipes the current timetable.

## Features

- Timetable for all classes, one class or one teacher; rebuilds itself after every change
- **Scheduler**: type a request in English or Arabic, or use "Build a request"; preview, then confirm; saved rules in plain sentences
- **Substitutes**: short-term (pick days) and long-term (reassign a teacher's classes) with ranked replacements and a one-sentence explanation
- Subject hours per grade (must total 35), classes, teachers, rules, and **Excel import** (template, preview, confirm)
- **Check**: re-checks every hard rule against the saved timetable, workload, gaps, AI insights
- English and Arabic (right to left), light and dark mode, works on a phone
- Settings: choose the AI model from a fixed list

## Tech stack

Python 3.12, FastAPI, OR-Tools (CP-SAT), SQLite, OpenRouter for the AI, and a plain HTML/CSS/JavaScript frontend
(no build step) served by the backend. Everything is described in [CONTRACT.md](CONTRACT.md).

## Run locally

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000 (API docs at http://localhost:8000/docs). Add `--reload` while developing.
Tests: `pip install -r requirements-dev.txt` then `pytest` (inside `backend/`).

Render runs the same thing (see `render.yaml`): `pip install -r backend/requirements.txt`, then
`cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`, health check `/api/health`, Python 3.12.7.

## Safety note

The AI key is **only** read from environment variables (`OPENROUTER_API_KEY`, optional `OPENROUTER_MODEL`), set in
Render's dashboard or in a git-ignored `.env` file at the repo root. It is never in the code, never in the repository,
never returned by the API and never typed into the app. Only shortened teacher names (first name and initial) are ever
sent to the AI. Without a key everything still works except the AI features.
