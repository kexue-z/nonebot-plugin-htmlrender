from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.adapters.takumi.cache import (
    SyncWeightedSingleflightLRU,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class _RecordingCacheObserver:
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


class _FailingCacheObserver:
    def record(
        self,
        cache: str,
        events: Mapping[str, int],
        entries: int,
        resident_bytes: int | None = None,
    ) -> None:
        del cache, events, entries, resident_bytes
        raise RuntimeError("observer down")


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


def test_weighted_cache_clear_detaches_inflight_factory() -> None:
    cache = SyncWeightedSingleflightLRU[str, str](max_entries=4, max_weight=16)
    first_started = threading.Event()
    release_first = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def factory() -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
            call = calls
        if call == 1:
            first_started.set()
            if not release_first.wait(timeout=2):
                raise AssertionError("test did not release the first factory")
            return "old"
        return "new"

    with ThreadPoolExecutor(max_workers=3) as executor:
        old_owner = executor.submit(
            cache.get_or_insert,
            "same",
            weight=1,
            factory=factory,
        )
        if not first_started.wait(timeout=1):
            raise AssertionError("first cache factory did not start")
        old_waiter = executor.submit(
            cache.get_or_insert,
            "same",
            weight=1,
            factory=factory,
        )
        deadline = time.monotonic() + 1
        while cache.stats().waits < 1 and time.monotonic() < deadline:
            time.sleep(0.001)
        if cache.stats().waits != 1:
            raise AssertionError("old waiter did not join the in-flight factory")

        cache.clear()
        assert (
            executor.submit(
                cache.get_or_insert,
                "same",
                weight=1,
                factory=factory,
            ).result(timeout=1)
            == "new"
        )
        release_first.set()
        assert old_owner.result(timeout=1) == "old"
        assert old_waiter.result(timeout=1) == "old"

    assert cache.get_or_insert("same", weight=1, factory=lambda: "unused") == "new"
    assert calls == 2
    assert cache.stats().entries == 1


def test_weighted_cache_old_error_after_clear_does_not_remove_new_inflight() -> None:
    cache = SyncWeightedSingleflightLRU[str, str](max_entries=4, max_weight=16)
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    release_second = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def factory() -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
            call = calls
        if call == 1:
            first_started.set()
            if not release_first.wait(timeout=2):
                raise AssertionError("test did not release the first factory")
            raise RuntimeError("old failed")
        if call == 2:
            second_started.set()
            if not release_second.wait(timeout=2):
                raise AssertionError("test did not release the second factory")
            return "new"
        raise AssertionError("unexpected cache factory call")

    def load() -> str:
        return cache.get_or_insert("same", weight=1, factory=factory)

    with ThreadPoolExecutor(max_workers=3) as executor:
        old_owner = executor.submit(load)
        if not first_started.wait(timeout=1):
            raise AssertionError("first cache factory did not start")
        old_waiter = executor.submit(load)
        deadline = time.monotonic() + 1
        while cache.stats().waits < 1 and time.monotonic() < deadline:
            time.sleep(0.001)
        if cache.stats().waits != 1:
            raise AssertionError("old waiter did not join the in-flight factory")

        cache.clear()
        new_owner = executor.submit(load)
        if not second_started.wait(timeout=1):
            raise AssertionError("second cache factory did not start")
        release_first.set()
        with pytest.raises(RuntimeError, match="old failed"):
            old_owner.result(timeout=1)
        with pytest.raises(RuntimeError, match="old failed"):
            old_waiter.result(timeout=1)
        assert not new_owner.done()
        release_second.set()
        assert new_owner.result(timeout=1) == "new"

    assert cache.get_or_insert("same", weight=1, factory=lambda: "unused") == "new"
    assert calls == 2
    assert cache.stats().entries == 1


def test_weighted_cache_exports_event_deltas_and_state() -> None:
    observer = _RecordingCacheObserver()
    cache = SyncWeightedSingleflightLRU[str, str](
        max_entries=1,
        max_weight=8,
        observer=observer,
        cache_name="takumi_compiled",
    )

    cache.get_or_insert("a", weight=3, factory=lambda: "A")
    cache.get_or_insert("a", weight=3, factory=lambda: "unused")
    cache.get_or_insert("b", weight=4, factory=lambda: "B")

    assert observer.calls[-1] == (
        "takumi_compiled",
        {"hit": 0, "miss": 1, "load": 1, "wait": 0, "eviction": 1},
        1,
        4,
    )


def test_weighted_cache_survives_failing_observer() -> None:
    cache = SyncWeightedSingleflightLRU[str, str](
        max_entries=4,
        max_weight=64,
        observer=_FailingCacheObserver(),
        cache_name="takumi_compiled",
    )

    assert cache.get_or_insert("a", weight=3, factory=lambda: "A") == "A"
    assert cache.get_or_insert("a", weight=3, factory=lambda: "unused") == "A"
    assert cache.stats().hits == 1
