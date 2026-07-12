from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, final

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)


class CacheObserver(Protocol):
    def record(
        self,
        cache: str,
        events: Mapping[str, int],
        entries: int,
        resident_bytes: int | None = None,
    ) -> None: ...


@final
class NoopCacheObserver:
    def record(
        self,
        cache: str,
        events: Mapping[str, int],
        entries: int,
        resident_bytes: int | None = None,
    ) -> None:
        del cache, events, entries, resident_bytes


def record_cache_observation(
    observer: CacheObserver,
    cache: str,
    events: Mapping[str, int],
    entries: int,
    resident_bytes: int | None = None,
) -> None:
    try:
        observer.record(cache, events, entries, resident_bytes)
    except Exception as error:
        logger.warning("Cache observer failed for %s: %s", cache, error)


__all__ = ["CacheObserver", "NoopCacheObserver", "record_cache_observation"]
