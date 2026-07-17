"""Shared admission budget for in-process raster scene work."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, final

import anyio

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .models import RasterScene


@final
class RasterWorkBudget:
    """Bound per-request pixels and total concurrent native allocations."""

    def __init__(self, *, max_pixels: int, max_concurrency: int) -> None:
        if max_pixels <= 0:
            raise ValueError("max_pixels must be positive")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._max_pixels = max_pixels
        self._limiter = anyio.CapacityLimiter(max_concurrency)

    @property
    def max_pixels(self) -> int:
        return self._max_pixels

    @property
    def max_concurrency(self) -> int:
        return int(self._limiter.total_tokens)

    @asynccontextmanager
    async def reserve(self, scene: RasterScene) -> AsyncIterator[None]:
        """Validate one scene before reserving a shared native-work slot."""
        pixels = scene.width * scene.height
        if pixels > self._max_pixels:
            raise InvalidRenderRequest(
                f"Raster scene contains {pixels} pixels, exceeding the configured "
                f"limit of {self._max_pixels}."
            )
        async with self._limiter:
            yield


__all__ = ["RasterWorkBudget"]
