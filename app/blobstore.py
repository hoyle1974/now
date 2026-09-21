"""Where attachment bytes live: a private Cloud Storage bucket in production, an
in-memory dict in tests and local dev (when ATTACHMENTS_BUCKET is unset).

Keys look like todos/{todo_id}/{attachment_id}. Metadata is kept on the todo,
so this layer only moves bytes."""
from __future__ import annotations

import contextlib
import datetime
import os


class MemoryStore:
    def __init__(self):
        self._objects: dict[str, tuple[bytes, str]] = {}
        self._times: dict[str, datetime.datetime] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._objects[key] = (data, content_type)
        self._times[key] = datetime.datetime.now(datetime.UTC)

    def get(self, key: str) -> tuple[bytes, str] | None:
        return self._objects.get(key)

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)
        self._times.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        for key in [k for k in self._objects if k.startswith(prefix)]:
            self.delete(key)

    def list_blobs(self, prefix: str) -> list[tuple[str, datetime.datetime]]:
        return [(k, self._times[k]) for k in sorted(self._objects) if k.startswith(prefix)]

    def keys(self) -> list[str]:
        return sorted(self._objects)


class GcsStore:
    def __init__(self, bucket_name: str):
        from google.cloud import storage  # imported lazily: tests never need it
        self._bucket = storage.Client().bucket(bucket_name)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._bucket.blob(key).upload_from_string(data, content_type=content_type)

    def get(self, key: str) -> tuple[bytes, str] | None:
        from google.cloud.exceptions import NotFound
        blob = self._bucket.blob(key)
        try:
            data = blob.download_as_bytes()
        except NotFound:
            return None
        return data, blob.content_type or "application/octet-stream"

    def delete(self, key: str) -> None:
        from google.cloud.exceptions import NotFound
        with contextlib.suppress(NotFound):
            self._bucket.blob(key).delete()

    def delete_prefix(self, prefix: str) -> None:
        for blob in self._bucket.list_blobs(prefix=prefix):
            blob.delete()

    def list_blobs(self, prefix: str) -> list[tuple[str, datetime.datetime]]:
        return [(b.name, b.time_created) for b in self._bucket.list_blobs(prefix=prefix)]


_store = None


def get_store():
    global _store
    if _store is None:
        bucket = os.environ.get("ATTACHMENTS_BUCKET")
        if not bucket and os.environ.get("K_SERVICE"):
            # On Cloud Run an in-memory store would silently lose every image on
            # the next restart, so refuse rather than pretend to save them.
            raise RuntimeError("ATTACHMENTS_BUCKET is not set (run scripts/create-bucket.sh)")
        _store = GcsStore(bucket) if bucket else MemoryStore()
    return _store


def use_memory() -> MemoryStore:
    """Swap in a fresh in-memory store (tests)."""
    global _store
    _store = MemoryStore()
    return _store


def key_for(todo_id: str, attachment_id: str) -> str:
    return f"todos/{todo_id}/{attachment_id}"


def todo_prefix(todo_id: str) -> str:
    return f"todos/{todo_id}/"
