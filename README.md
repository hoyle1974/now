# Day 11 — personal project: a todo app, your design

Stack: FastAPI + server-rendered Jinja2 HTML (no separate JS frontend)
+ stdlib `sqlite3` for persistence. No ORM.

## Setup

```bash
cd day11
python3.13 -m venv .venv       # separate venv from the rest of the repo, optional
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## What's here

- `app/main.py` — FastAPI app instance and Jinja2 template setup. No
  routes yet.
- `app/db.py` — empty. This is where your `sqlite3` connection
  handling and schema go.
- `templates/base.html` — a bare HTML shell (no styling, no logic) so
  `main.py` has something to render if you want to sanity-check the
  server boots and Jinja2 wiring works before writing real pages.
- `static/` — empty, for any CSS/JS you want to add later.

## What's NOT here, on purpose

No models, no schema, no routes, no feature list. This is your
project — scope, data model, and feature set are your calls. From here
on, ask specific Python/API questions as you go; answers will point
you at the right stdlib/library call or explain a mechanic, not design
or write the feature for you.
