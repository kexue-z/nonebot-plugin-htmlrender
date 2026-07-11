from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.resources.observation import (
    NoopCacheObserver,
    get_cache_observer,
    record_cache_observation,
    register_cache_observer_provider,
)

if TYPE_CHECKING:
    from tests.resources.conftest import FailingCacheObserver, RecordingCacheObserver


def test_default_observer_is_noop() -> None:
    previous = register_cache_observer_provider(None)
    try:
        assert isinstance(get_cache_observer(), NoopCacheObserver)
    finally:
        register_cache_observer_provider(previous)


def test_registration_returns_previous_provider(
    recording_observer: RecordingCacheObserver,
) -> None:
    first = register_cache_observer_provider(lambda: recording_observer)
    try:
        assert get_cache_observer() is recording_observer
        second = register_cache_observer_provider(None)
        assert second is not None
        assert second() is recording_observer
    finally:
        register_cache_observer_provider(first)


def test_failing_provider_falls_back_to_noop() -> None:
    def broken_provider() -> NoopCacheObserver:
        raise RuntimeError("provider down")

    previous = register_cache_observer_provider(broken_provider)
    try:
        assert isinstance(get_cache_observer(), NoopCacheObserver)
    finally:
        register_cache_observer_provider(previous)


def test_record_cache_observation_contains_observer_failure(
    failing_observer: FailingCacheObserver,
) -> None:
    record_cache_observation(failing_observer, "resource", {"hit": 1}, 1, 10)


def test_record_cache_observation_passes_through(
    recording_observer: RecordingCacheObserver,
) -> None:
    record_cache_observation(recording_observer, "resource", {"hit": 2}, 3, 64)

    assert recording_observer.calls == [("resource", {"hit": 2}, 3, 64)]
