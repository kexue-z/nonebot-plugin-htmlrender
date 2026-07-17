"""Narrow typed facade over the optional, non-PEP-561 HTMLKit package."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from importlib import import_module
from typing import Protocol, TypeAlias, cast

from nonebot_plugin_htmlrender.raster import RasterImageFormat  # noqa: TC001

ImageFetcher: TypeAlias = Callable[[str], Awaitable[bytes | None]]
StylesheetFetcher: TypeAlias = Callable[[str], Awaitable[str | None]]


class HtmlkitApi(Protocol):
    async def html_to_pic(
        self,
        html: str,
        *,
        base_url: str,
        dpi: float,
        max_width: float,
        device_height: float,
        default_font_size: float,
        font_name: str,
        allow_refit: bool,
        image_format: RasterImageFormat,
        jpeg_quality: int,
        lang: str,
        culture: str,
        img_fetch_fn: ImageFetcher,
        css_fetch_fn: StylesheetFetcher,
        native_data_scheme: bool,
    ) -> bytes: ...


def load_htmlkit_api() -> HtmlkitApi:
    """Load the selected optional backend at the last responsible moment."""
    return cast("HtmlkitApi", import_module("nonebot_plugin_htmlkit"))


__all__ = [
    "HtmlkitApi",
    "ImageFetcher",
    "StylesheetFetcher",
    "load_htmlkit_api",
]
