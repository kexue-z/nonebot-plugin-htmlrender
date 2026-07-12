from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping


class RecordingCacheObserver:
    """Cache observer fake capturing every injected observation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, int], int, int | None]] = []

    def record(
        self,
        cache: str,
        events: Mapping[str, int],
        entries: int,
        resident_bytes: int | None = None,
    ) -> None:
        self.calls.append((cache, dict(events), entries, resident_bytes))


class FailingCacheObserver:
    """Cache observer fake proving instrumentation is not a correctness seam."""

    def record(
        self,
        cache: str,
        events: Mapping[str, int],
        entries: int,
        resident_bytes: int | None = None,
    ) -> None:
        del cache, events, entries, resident_bytes
        raise RuntimeError("observer down")


@pytest.fixture
def recording_observer() -> RecordingCacheObserver:
    return RecordingCacheObserver()


@pytest.fixture
def failing_observer() -> FailingCacheObserver:
    return FailingCacheObserver()
