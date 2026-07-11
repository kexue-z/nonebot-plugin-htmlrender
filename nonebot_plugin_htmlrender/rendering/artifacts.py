"""Typed artifacts returned by the rendering application."""

from __future__ import annotations

from dataclasses import dataclass

_MEDIA_TYPE_OVERRIDES: dict[str, str] = {
    "svg": "image/svg+xml",
}


@dataclass(frozen=True, slots=True)
class RenderedImage:
    """Raster output of a render operation."""

    data: bytes
    format: str
    width: int | None = None
    height: int | None = None

    @property
    def media_type(self) -> str:
        return _MEDIA_TYPE_OVERRIDES.get(self.format, f"image/{self.format}")

    def __bytes__(self) -> bytes:
        return self.data


@dataclass(frozen=True, slots=True)
class RenderedHtml:
    """HTML output of a template-to-html render operation."""

    content: str

    def __str__(self) -> str:
        return self.content
