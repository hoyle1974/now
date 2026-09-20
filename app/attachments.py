"""Checks for uploaded images. The client's Content-Type and filename are never
trusted: the type comes from the file's leading bytes, and only raster formats
that can't carry script are allowed (SVG is deliberately not one of them)."""
from __future__ import annotations

MAX_NAME_LEN = 200


def sniff_image_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def clean_name(raw: str | None) -> str:
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = "".join(ch for ch in name if ch.isprintable())
    return name[:MAX_NAME_LEN] or "image"
