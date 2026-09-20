"""require_user gate: token required, only ALLOWED_EMAIL accepted."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import auth


def _request(path="/todos/root", authorization=None, widget=None, method="GET"):
    headers = [(b"authorization", authorization.encode())] if authorization else []
    if widget:
        headers.append((b"x-widget-token", widget.encode()))
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "query_string": b""})


def test_health_is_public():
    auth.require_user(_request("/health"))


def test_missing_token_is_401():
    with pytest.raises(HTTPException) as e:
        auth.require_user(_request())
    assert e.value.status_code == 401


@pytest.mark.parametrize("claims,status", [
    ({"email": "you@example.com", "email_verified": True}, None),
    ({"email": "Hoyle.Hoyle@gmail.com", "email_verified": True}, None),
    ({"email": "other@gmail.com", "email_verified": True}, 403),
    ({"email": "you@example.com", "email_verified": False}, 403),
])
def test_email_allowlist(monkeypatch, claims, status):
    monkeypatch.setattr(auth.firebase_admin, "_apps", {"x": 1})
    monkeypatch.setattr(auth.fb_auth, "verify_id_token", lambda t: claims)
    if status is None:
        auth.require_user(_request(authorization="Bearer tok"))
    else:
        with pytest.raises(HTTPException) as e:
            auth.require_user(_request(authorization="Bearer tok"))
        assert e.value.status_code == status


def test_bad_token_is_401(monkeypatch):
    monkeypatch.setattr(auth.firebase_admin, "_apps", {"x": 1})
    def boom(t): raise ValueError("bad")
    monkeypatch.setattr(auth.fb_auth, "verify_id_token", boom)
    with pytest.raises(HTTPException) as e:
        auth.require_user(_request(authorization="Bearer tok"))
    assert e.value.status_code == 401


def test_widget_token_unlocks_only_next_up(monkeypatch):
    monkeypatch.setattr(auth, "WIDGET_TOKEN", "s3cret")
    auth.require_user(_request("/todos/next", widget="s3cret"))
    for kwargs in ({"path": "/todos/root"}, {"path": "/todos/next", "method": "POST"},
                   {"path": "/todos/next", "widget": "wrong"}):
        with pytest.raises(HTTPException) as e:
            auth.require_user(_request(**{"widget": "s3cret", **kwargs}))
        assert e.value.status_code == 401


def test_widget_token_off_when_unset(monkeypatch):
    monkeypatch.setattr(auth, "WIDGET_TOKEN", "")
    with pytest.raises(HTTPException):
        auth.require_user(_request("/todos/next", widget=""))
