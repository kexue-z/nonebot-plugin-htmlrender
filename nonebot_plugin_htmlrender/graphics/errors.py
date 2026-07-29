"""Stable errors exposed by neutral raster-scene capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.errors import RenderingError

if TYPE_CHECKING:
    from .models import GraphicsBackendName


class RasterBackendUnavailable(RenderingError):
    """A configured raster-scene backend cannot run in this environment."""

    def __init__(
        self,
        backend: GraphicsBackendName,
        detail: str,
        *,
        source: BaseException | None = None,
    ) -> None:
        super().__init__(
            f"Raster backend `{backend}` is unavailable: {detail}",
            source=source,
        )
        self.backend = backend


class RasterBackendExecutionError(RenderingError):
    """A raster-scene backend failed without leaking a native exception type."""

    def __init__(
        self,
        backend: GraphicsBackendName,
        detail: str,
        *,
        source: BaseException | None = None,
    ) -> None:
        super().__init__(f"Raster backend `{backend}` failed: {detail}", source=source)
        self.backend = backend


__all__ = ["RasterBackendExecutionError", "RasterBackendUnavailable"]
