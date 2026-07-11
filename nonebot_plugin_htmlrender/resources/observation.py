"""Cache observation seam for the resource layer.

The resource layer never imports telemetry adapters; it reports cache
statistics through an injected ``CacheObserver``. Observer failures are
contained here and never reach cache callers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, final

from nonebot.log import logger

if TYPE_CHECKING:
    from collections.abc import Mapping


class CacheObserver(Protocol):
    """Receives low-cardinality cache statistics deltas."""

    def record(
        self,
        cache: str,
        events: Mapping[str, int],
        entries: int,
        resident_bytes: int | None = None,
    ) -> None: ...


@final
class NoopCacheObserver:
    """Observer that discards every cache statistics delta."""

    def record(
        self,
        cache: str,  # noqa: ARG002 -- protocol-conforming no-op
        events: Mapping[str, int],  # noqa: ARG002 -- protocol-conforming no-op
        entries: int,  # noqa: ARG002 -- protocol-conforming no-op
        resident_bytes: int | None = None,  # noqa: ARG002 -- protocol-conforming no-op
    ) -> None:
        return None


_NOOP_OBSERVER = NoopCacheObserver()

CacheObserverProvider = Callable[[], "CacheObserver"]

_observer_provider: CacheObserverProvider | None = None


def register_cache_observer_provider(
    provider: CacheObserverProvider | None,
) -> CacheObserverProvider | None:
    """Install the process-level observer provider; returns the previous one."""
    global _observer_provider  # noqa: PLW0603
    previous = _observer_provider
    _observer_provider = provider
    return previous


def get_cache_observer() -> CacheObserver:
    """Return the composed cache observer, falling back to a no-op."""
    provider = _observer_provider
    if provider is None:
        return _NOOP_OBSERVER
    try:
        return provider()
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.resources]</d> Cache observer provider failed: "
            "<r>{error}</r>.",
            error=error,
        )
        return _NOOP_OBSERVER


def record_cache_observation(
    observer: CacheObserver,
    cache: str,
    events: Mapping[str, int],
    entries: int,
    resident_bytes: int | None = None,
) -> None:
    """Record through the observer, containing any observer failure."""
    try:
        observer.record(cache, events, entries, resident_bytes)
    except Exception as error:
        logger.opt(colors=True).warning(
            "<d>[htmlrender.resources]</d> Cache observer failed for "
            "<c>{cache}</c>: <r>{error}</r>.",
            cache=cache,
            error=error,
        )


__all__ = [
    "CacheObserver",
    "CacheObserverProvider",
    "NoopCacheObserver",
    "get_cache_observer",
    "record_cache_observation",
    "register_cache_observer_provider",
]
