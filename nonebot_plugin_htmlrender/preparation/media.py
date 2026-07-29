"""Shared media-type resolution for prepared assets."""

from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import PreparedAsset


def sniff_media_type(payload: bytes) -> str:
    """Classify a binary payload by magic bytes, octet-stream otherwise."""
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    if payload.startswith(b"wOF2"):
        return "font/woff2"
    if payload.startswith(b"wOFF"):
        return "font/woff"
    if payload.lstrip().startswith(b"<svg"):
        return "image/svg+xml"
    return "application/octet-stream"


def guess_asset_media_type(asset: PreparedAsset) -> str | None:
    """Return the declared media type or a filename-based guess."""
    return asset.media_type or mimetypes.guess_type(asset.source)[0]


__all__ = ["guess_asset_media_type", "sniff_media_type"]
