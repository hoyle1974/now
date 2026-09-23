"""The client's sync engine only sends fields on its PATCH_FIELDS list, so a field
the server accepts but the client omits is silently dropped on save (calendar_url
was, and every server test still passed). Keep the two lists in step."""
import re
from pathlib import Path

from app import models

# Changed through their own routes, never through a field PATCH.
SERVER_ONLY = {"deleted"}


def test_client_patch_fields_match_todo_update():
    src = (Path(__file__).parent.parent / "web" / "sync.js").read_text()
    block = re.search(r"const PATCH_FIELDS = \[(.*?)\];", src, re.S).group(1)
    client = set(re.findall(r'"(\w+)"', block))
    assert client == set(models.TodoUpdate.model_fields) - SERVER_ONLY
