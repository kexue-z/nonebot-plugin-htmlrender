from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.resources.observation import (
    NoopCacheObserver,
    record_cache_observation,
)

if TYPE_CHECKING:
    from tests.resources.conftest import (
        FailingCacheObserver,
        RecordingCacheObserver,
    )


def test_noop_observer_accepts_complete_observation() -> None:
    NoopCacheObserver().record(
        "resource",
        {"hit": 1, "miss": 2},
        entries=3,
        resident_bytes=128,
    )


def test_observation_is_sent_only_to_injected_instance(
    recording_observer: RecordingCacheObserver,
) -> None:
    other = RecordingObserver()

    record_cache_observation(
        recording_observer,
        "resource",
        {"load": 1},
        entries=1,
        resident_bytes=64,
    )

    assert recording_observer.calls == [
        ("resource", {"load": 1}, 1, 64),
    ]
    assert other.calls == []


def test_observation_failure_never_changes_cache_correctness(
    failing_observer: FailingCacheObserver,
) -> None:
    record_cache_observation(
        failing_observer,
        "resource",
        {"hit": 1},
        entries=1,
    )


class RecordingObserver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, int], int, int | None]] = []

    def record(
        self,
        cache: str,
        events: dict[str, int],
        entries: int,
        resident_bytes: int | None = None,
    ) -> None:
        self.calls.append((cache, events, entries, resident_bytes))
