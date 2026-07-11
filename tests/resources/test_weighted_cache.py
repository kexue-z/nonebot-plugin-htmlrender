from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.resources.weighted_cache import (
    SyncWeightedSingleflightLRU,
)

if TYPE_CHECKING:
    from tests.resources.conftest import FailingCacheObserver, RecordingCacheObserver


def test_weighted_cache_enforces_entry_and_weight_limits() -> None:
    cache = SyncWeightedSingleflightLRU[str, str](max_entries=2, max_weight=6)

    assert cache.get_or_insert("a", weight=3, factory=lambda: "A") == "A"
    assert cache.get_or_insert("b", weight=3, factory=lambda: "B") == "B"
    assert cache.get_or_insert("a", weight=3, factory=lambda: "unused") == "A"
    assert cache.get_or_insert("c", weight=3, factory=lambda: "C") == "C"

    stats = cache.stats()
    assert stats.entries == 2
    assert stats.resident_weight == 6
    assert stats.hits == 1
    assert stats.evictions == 1


def test_weighted_cache_oversize_and_zero_capacity_bypass_residency() -> None:
    oversized = SyncWeightedSingleflightLRU[str, str](max_entries=2, max_weight=2)
    disabled = SyncWeightedSingleflightLRU[str, str](max_entries=0, max_weight=8)

    assert oversized.get_or_insert("a", weight=3, factory=lambda: "A") == "A"
    assert disabled.get_or_insert("a", weight=1, factory=lambda: "A") == "A"
    assert oversized.stats().entries == 0
    assert disabled.stats().entries == 0


def test_weighted_cache_singleflights_same_key() -> None:
    cache = SyncWeightedSingleflightLRU[str, object](max_entries=4, max_weight=16)
    calls = 0
    calls_lock = threading.Lock()

    def factory() -> object:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.03)
        return object()

    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(
            executor.map(
                lambda _: cache.get_or_insert("same", weight=1, factory=factory),
                range(8),
            )
        )

    assert calls == 1
    assert all(value is values[0] for value in values)
    assert cache.stats().waits == 7


def test_weighted_cache_broadcasts_factory_errors() -> None:
    cache = SyncWeightedSingleflightLRU[str, str](max_entries=4, max_weight=16)
    calls = 0
    calls_lock = threading.Lock()
    factory_started = threading.Event()
    release_factory = threading.Event()

    def factory() -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
        factory_started.set()
        if not release_factory.wait(timeout=2):
            raise AssertionError("test did not release the cache factory")
        raise RuntimeError("compile failed")

    def load() -> str:
        with pytest.raises(RuntimeError, match="compile failed"):
            cache.get_or_insert("same", weight=1, factory=factory)
        return "failed"

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(load) for _ in range(6)]
        if not factory_started.wait(timeout=1):
            raise AssertionError("cache factory did not start")
        deadline = time.monotonic() + 1
        try:
            while cache.stats().waits < 5 and time.monotonic() < deadline:
                time.sleep(0.001)
            if cache.stats().waits != 5:
                raise AssertionError("not all callers joined the same inflight load")
        finally:
            release_factory.set()
        assert [future.result() for future in futures] == ["failed"] * 6

    assert calls == 1
    assert cache.stats().entries == 0


def test_weighted_cache_exports_event_deltas_and_state(
    recording_observer: RecordingCacheObserver,
) -> None:
    cache = SyncWeightedSingleflightLRU[str, str](
        max_entries=1,
        max_weight=8,
        observer=recording_observer,
        cache_name="takumi_compiled",
    )

    cache.get_or_insert("a", weight=3, factory=lambda: "A")
    cache.get_or_insert("a", weight=3, factory=lambda: "unused")
    cache.get_or_insert("b", weight=4, factory=lambda: "B")

    assert recording_observer.calls[-1] == (
        "takumi_compiled",
        {"hit": 0, "miss": 1, "load": 1, "wait": 0, "eviction": 1},
        1,
        4,
    )


def test_weighted_cache_survives_failing_observer(
    failing_observer: FailingCacheObserver,
) -> None:
    cache = SyncWeightedSingleflightLRU[str, str](
        max_entries=4,
        max_weight=64,
        observer=failing_observer,
        cache_name="takumi_compiled",
    )

    assert cache.get_or_insert("a", weight=3, factory=lambda: "A") == "A"
    assert cache.get_or_insert("a", weight=3, factory=lambda: "unused") == "A"
    assert cache.stats().hits == 1
