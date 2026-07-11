from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


class RecordingCacheObserver:
    """Cache observer fake capturing every recorded delta."""

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
    """Cache observer fake that always raises."""

    def record(
        self,
        cache: str,  # noqa: ARG002 -- protocol-conforming failure fake
        events: Mapping[str, int],  # noqa: ARG002 -- protocol-conforming failure fake
        entries: int,  # noqa: ARG002 -- protocol-conforming failure fake
        resident_bytes: int | None = None,  # noqa: ARG002 -- protocol-conforming failure fake
    ) -> None:
        raise RuntimeError("observer down")


@pytest.fixture
def recording_observer() -> RecordingCacheObserver:
    """A recording observer for direct constructor injection."""
    return RecordingCacheObserver()


@pytest.fixture
def failing_observer() -> FailingCacheObserver:
    """An observer that raises on every record call."""
    return FailingCacheObserver()


@pytest.fixture
def cache_observer() -> Iterator[RecordingCacheObserver]:
    """Install a recording observer as the process provider for one test."""
    # Imported lazily: initial conftests load before NoneBot is initialized.
    from nonebot_plugin_htmlrender.resources.observation import (  # noqa: PLC0415
        register_cache_observer_provider,
    )

    observer = RecordingCacheObserver()
    previous = register_cache_observer_provider(lambda: observer)
    yield observer
    register_cache_observer_provider(previous)
