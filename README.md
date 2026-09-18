# now — A Personal Todo App

A minimal todo app built with **FastAPI + server-rendered Jinja2 HTML** + **SQLite** (migrating to **Firestore** on GCP CloudRun).

Designed as a learning project, but simple enough to actually use day-to-day.

## Stack

- **Backend:** FastAPI + Jinja2 (server-rendered HTML, no separate JS frontend)
- **Database:** SQLite (current) → Firestore (planned)
- **Deployment:** Local dev → GCP CloudRun + Firestore

## Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Server runs at `http://localhost:8000`

## What's here

- `app/main.py` — FastAPI app with routes and Jinja2 templating
- `app/db.py` — SQLite connection and schema (will migrate to Firestore)
- `templates/` — Jinja2 templates for UI
- `static/` — CSS/JS and other assets
- `web/` — Frontend JavaScript for drag-and-drop and interactions
- `scripts/` — Utility scripts
- `docs/` — Project documentation

## Next: GCP Migration

This app will be deployed to GCP CloudRun with Firestore as the database using `zilch-gcp` for infrastructure automation.
