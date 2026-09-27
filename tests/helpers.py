from app import auth, db, tenant

TEST_USER = "me@example.com"
OTHER_USER = "other@example.com"


def wipe_users() -> None:
    """Empty the emulator's per-user data (needs db.init() first)."""
    client = db.get_conn()
    # users/{email} parent docs never exist (only their subcollections), which is exactly
    # what list_documents() returns; delete each subcollection through it. Shares have a
    # real parent doc (the share record) as well as subcollections.
    for kind in ("users", "shares", "shares_meta"):
        for parent in client.collection(kind).list_documents():
            for sub in parent.collections():
                for doc in sub.stream():
                    doc.reference.delete()
            parent.delete()


def act_as(app, email: str = TEST_USER) -> None:
    """Skip real sign-in in TestClient tests and bind `email` as the request's user."""
    async def _bind() -> None:
        tenant.set_user(email)
    app.dependency_overrides[auth.require_user] = lambda: None
    app.dependency_overrides[auth.bind_user] = _bind
