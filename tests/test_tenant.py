import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import auth, tenant


def test_current_raises_when_unbound():
    with pytest.raises(RuntimeError):
        tenant.current()


def test_as_user_binds_lowercases_and_restores():
    with tenant.as_user(" Kid@Example.com "):
        assert tenant.current() == "kid@example.com"
    with pytest.raises(RuntimeError):
        tenant.current()


def _req(path="/todos/root", authorization=None, widget=None, method="GET"):
    headers = [(b"authorization", authorization.encode())] if authorization else []
    if widget:
        headers.append((b"x-widget-token", widget.encode()))
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "query_string": b""})


def _two_users(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", ("me@example.com", "kid@example.com"))
    monkeypatch.setattr(auth.firebase_admin, "_apps", {"x": 1})
    monkeypatch.setattr(auth.fb_auth, "verify_id_token",
                        lambda t: {"email": f"{t}@example.com", "email_verified": True})


def test_every_allowed_email_passes_and_is_recorded(monkeypatch):
    _two_users(monkeypatch)
    for who in ("me", "kid"):
        r = _req(authorization=f"Bearer {who}")
        auth.require_user(r)
        assert r.state.user == f"{who}@example.com"


def test_email_not_on_the_list_is_403(monkeypatch):
    _two_users(monkeypatch)
    with pytest.raises(auth.HTTPException) as e:
        auth.require_user(_req(authorization="Bearer stranger"))
    assert e.value.status_code == 403


def test_widget_token_acts_as_owner(monkeypatch):
    _two_users(monkeypatch)
    monkeypatch.setattr(auth, "WIDGET_TOKEN", "s3cret")
    r = _req("/todos/next", widget="s3cret")
    auth.require_user(r)
    assert r.state.user == "me@example.com"


def test_calendar_feed_path_is_owner_only(monkeypatch):
    _two_users(monkeypatch)
    monkeypatch.setattr(auth, "CALENDAR_TOKEN", "a" * 20)
    assert auth.calendar_feed_path("me@example.com") == f"/calendar/{'a' * 20}.ics"
    assert auth.calendar_feed_path("kid@example.com") is None


def test_legacy_single_email_env_is_still_read():
    assert auth._parse_emails("Me@Example.com") == ("me@example.com",)
    assert auth._parse_emails("a@x.com; b@x.com,c@x.com  a@x.com") == ("a@x.com", "b@x.com", "c@x.com")


def test_bound_user_reaches_a_sync_route_in_the_threadpool(monkeypatch):
    """The risk this plan rests on: a ContextVar set by the async dependency must be
    visible inside a sync route function (which FastAPI runs in a worker thread)."""
    _two_users(monkeypatch)
    mini = FastAPI(dependencies=[Depends(auth.require_user), Depends(auth.bind_user)])

    @mini.get("/whoami")
    def whoami() -> dict:
        return {"user": tenant.current()}

    c = TestClient(mini)
    assert c.get("/whoami", headers={"Authorization": "Bearer kid"}).json() == {"user": "kid@example.com"}
    assert c.get("/whoami", headers={"Authorization": "Bearer me"}).json() == {"user": "me@example.com"}
