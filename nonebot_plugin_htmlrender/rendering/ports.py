"""Ports connecting the rendering application to provider adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from nonebot_plugin_htmlrender.resources.observation import (
    CacheObserver as CacheObserver,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractContextManager

    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        RasterOptions,
    )

    from .requests import ResourcePolicy


class PreparedHtmlExecutor(Protocol):
    """Executes a prepared HTML document into raster bytes."""

    async def execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resource_policy: ResourcePolicy | None = None,
        timeout_seconds: float | None = None,
    ) -> bytes: ...


class OperationObserver(Protocol):
    """Observes one named operation; must never raise into business flow."""

    def observe(
        self,
        operation: str,
        attributes: Mapping[str, str],
    ) -> AbstractContextManager[None]: ...


class ApplicationLifecycle(Protocol):
    """Startup, probe, and shutdown of the composed provider runtime."""

    async def startup(self) -> None: ...

    async def probe(self) -> None: ...

    async def aclose(self) -> None: ...
