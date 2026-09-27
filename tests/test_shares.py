"""Share registry: share docs, membership, write rights, view state (app/shares.py)."""
import datetime

import pytest

from app import db, shares, tenant
from tests.helpers import OTHER_USER, TEST_USER, wipe_users


@pytest.fixture(autouse=True)
def setup():
    db.init()
    wipe_users()
    with tenant.as_user(TEST_USER):
        yield
    db.teardown()


def _share(**kw) -> shares.Share:
    base = dict(id="s1", owner=TEST_USER, members="all", mode="rw", state="active")
    base.update(kw)
    return shares.Share(**base)


def test_put_and_get_round_trip():
    shares.put(_share())
    got = shares.get("s1")
    assert got.owner == TEST_USER and got.mode == "rw" and got.state == "active"
    assert shares.get("missing") is None


def test_members_all_means_every_allowed_email():
    s = _share()
    assert shares.is_member(s, TEST_USER) and shares.is_member(s, OTHER_USER)
    assert not shares.is_member(s, "stranger@example.com")
    listed = _share(members=[TEST_USER])
    assert shares.is_member(listed, TEST_USER) and not shares.is_member(listed, OTHER_USER)


def test_can_write_matrix():
    assert shares.can_write(_share(mode="ro"), TEST_USER) is True       # owner
    assert shares.can_write(_share(mode="ro"), OTHER_USER) is False     # read-only member
    assert shares.can_write(_share(mode="rw"), OTHER_USER) is True      # can-edit member
    assert shares.can_write(_share(mode="rw"), "stranger@example.com") is False


def test_set_mode_bumps_meta_rev():
    shares.put(_share())
    before = shares.meta_rev()
    shares.set_mode("s1", "ro")
    assert shares.get("s1").mode == "ro"
    assert shares.meta_rev() == before + 1


def test_active_shares_skips_other_states():
    shares.put(_share())
    shares.put(_share(id="s2", state="unshared", returned_to=TEST_USER))
    assert [s.id for s in shares.active_shares()] == ["s1"]


def test_view_state_round_trip_and_expiry_field():
    shares.set_collapsed(OTHER_USER, "s1", "n1", True)
    shares.set_collapsed(OTHER_USER, "s1", "n2", True)
    shares.set_collapsed(OTHER_USER, "s1", "n1", False)
    assert shares.get_view_state(OTHER_USER, "s1") == {"n2"}
    assert shares.get_view_state(TEST_USER, "s1") == set()
    doc = db.user_ref(OTHER_USER).collection("view_state").document("s1").get().to_dict()
    left = doc["expires_at"] - datetime.datetime.now(datetime.UTC)
    assert datetime.timedelta(days=89) < left <= datetime.timedelta(days=90)


def test_sharing_enabled_reads_env(monkeypatch):
    from app import auth
    monkeypatch.delenv("SHARING_ENABLED", raising=False)
    assert auth.sharing_enabled() is False
    monkeypatch.setenv("SHARING_ENABLED", "1")
    assert auth.sharing_enabled() is True
