"""Ports connecting the rendering application to provider adapters."""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003
from contextlib import AbstractContextManager  # noqa: TC003
from typing import Protocol

from nonebot_plugin_htmlrender.preparation.models import (  # noqa: TC001
    PreparedHtml,
    RasterOptions,
)
from nonebot_plugin_htmlrender.resources.observation import (
    CacheObserver as CacheObserver,
)

# Public protocol annotations must remain resolvable through get_type_hints().
from .artifacts import RenderedImage  # noqa: TC001
from .requests import ResourcePolicy  # noqa: TC001


class PreparedHtmlExecutor(Protocol):
    """Executes a prepared HTML document into a validated raster artifact."""

    async def execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resource_policy: ResourcePolicy | None = None,
        timeout_seconds: float | None = None,
    ) -> RenderedImage: ...


class OperationObserver(Protocol):
    """Observes one named operation; must never raise into business flow."""

    def observe(
        self,
        operation: str,
        attributes: Mapping[str, str],
    ) -> AbstractContextManager[None]: ...


class ApplicationLifecycle(Protocol):
    """Startup, probe, and shutdown of the composed provider runtime.

    Contract for provider adapters:

    - ``compose`` (upstream of this port) performs no I/O and acquires no
      runtime resources; only ``startup`` may.
    - ``startup`` is failure-atomic and retryable: on error the provider is
      left equivalent to not started, and a later ``startup`` may succeed as
      long as any rollback fully succeeded. If rollback itself fails the
      composition is poisoned and further ``startup`` must raise
      ``ProviderLifecycleError``.
    - ``probe`` never changes ownership; it only exercises a started runtime.
    - ``aclose`` is idempotent over not-started, partially-started, started
      and poisoned states, and at least attempts to release every resource
      it acquired.
    """

    async def startup(self) -> None: ...

    async def probe(self) -> None: ...

    async def aclose(self) -> None: ...
