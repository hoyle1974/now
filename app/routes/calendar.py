"""The iCalendar feed."""
from __future__ import annotations

from fastapi import APIRouter, Response

from app import auth, db, ics

router = APIRouter()

@router.get("/calendar/link")
def calendar_link() -> dict:
    """For the More panel (signed in): where the calendar feed lives, or enabled=false."""
    path = auth.calendar_feed_path()
    return {"enabled": path is not None, "path": path}

@router.get("/calendar/{token}.ics", response_model=None)
def calendar_feed(token: str) -> Response:
    """Read-only iCalendar feed of open dated todos. The token in the path is checked
    by require_user (app/auth.py); the parameter is only there to shape the route."""
    _, todos_by_id = db.get_tree(db.get_rev())
    return Response(ics.build_calendar(todos_by_id), media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, max-age=300",
                             "Content-Disposition": 'inline; filename="now.ics"'})
