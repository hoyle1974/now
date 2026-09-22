"""require_user gate: token required, only an ALLOWED_EMAILS entry accepted."""
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
    ({"email": "me@example.com", "email_verified": True}, None),
    ({"email": "Me@Example.com", "email_verified": True}, None),
    ({"email": "other@gmail.com", "email_verified": True}, 403),
    ({"email": "me@example.com", "email_verified": False}, 403),
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


def test_widget_token_non_ascii_header_is_401_not_500(monkeypatch):
    monkeypatch.setattr(auth, "WIDGET_TOKEN", "s3cret")
    with pytest.raises(HTTPException) as e:
        auth.require_user(_request("/todos/next", widget="é"))
    assert e.value.status_code == 401


def test_unset_allowed_email_denies_everyone_and_fails_startup(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", ())
    monkeypatch.setattr(auth.fb_auth, "verify_id_token", lambda t: {"email": "", "email_verified": True})
    monkeypatch.setattr(auth.firebase_admin, "_apps", {"x": 1})
    with pytest.raises(HTTPException) as e:
        auth.require_user(_request(authorization="Bearer t"))
    assert e.value.status_code == 403
    with pytest.raises(RuntimeError):
        auth.check_config()
