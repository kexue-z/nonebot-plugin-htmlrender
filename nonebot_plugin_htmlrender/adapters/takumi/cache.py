"""Thread-safe weighted cache for Takumi native compilation results."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading
from typing import TYPE_CHECKING, Generic, TypeVar

from nonebot_plugin_htmlrender.resources.observation import record_cache_observation

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot_plugin_htmlrender.resources.observation import CacheObserver

K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True, slots=True)
class WeightedCacheStats:
    entries: int
    resident_weight: int
    hits: int
    misses: int
    loads: int
    waits: int
    evictions: int


@dataclass(slots=True)
class _Entry(Generic[V]):
    value: V
    weight: int


@dataclass(slots=True)
class _InflightResult(Generic[V]):
    value: V


@dataclass(slots=True)
class _Inflight(Generic[V]):
    event: threading.Event
    epoch: int
    result: _InflightResult[V] | None = None
    error: BaseException | None = None
    completed: bool = False


class SyncWeightedSingleflightLRU(Generic[K, V]):
    """Bounded LRU that compiles different keys concurrently."""

    def __init__(
        self,
        *,
        max_entries: int,
        max_weight: int,
        observer: CacheObserver | None = None,
        cache_name: str | None = None,
    ) -> None:
        if max_entries < 0 or max_weight < 0:
            raise ValueError("Weighted cache limits must not be negative")
        self.max_entries = max_entries
        self.max_weight = max_weight
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()
        self._inflight: dict[K, _Inflight[V]] = {}
        self._epoch = 0
        self._resident_weight = 0
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._loads = 0
        self._waits = 0
        self._evictions = 0
        self._observer = observer
        self._cache_name = cache_name
        self._reported_hits = 0
        self._reported_misses = 0
        self._reported_loads = 0
        self._reported_waits = 0
        self._reported_evictions = 0

    def get_or_insert(self, key: K, *, weight: int, factory: Callable[[], V]) -> V:
        try:
            return self._get_or_insert(key, weight=weight, factory=factory)
        finally:
            self._export_metrics()

    def _get_or_insert(self, key: K, *, weight: int, factory: Callable[[], V]) -> V:
        if weight < 0:
            raise ValueError("Cache entry weight must not be negative")
        owner = False
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                self._hits += 1
                return entry.value
            inflight = self._inflight.get(key)
            if inflight is None:
                inflight = _Inflight(event=threading.Event(), epoch=self._epoch)
                self._inflight[key] = inflight
                self._misses += 1
                owner = True
            else:
                self._waits += 1

        if not owner:
            inflight.event.wait()
            if inflight.error is not None:
                raise inflight.error
            if not inflight.completed:
                return self._get_or_insert(key, weight=weight, factory=factory)
            if inflight.result is None:
                return self._get_or_insert(key, weight=weight, factory=factory)
            return inflight.result.value

        try:
            value = factory()
        except BaseException as error:
            with self._lock:
                if self._inflight.get(key) is inflight:
                    self._inflight.pop(key, None)
                inflight.error = error
                inflight.completed = True
                inflight.event.set()
            raise

        with self._lock:
            self._loads += 1
            current = self._inflight.get(key)
            if current is inflight:
                self._inflight.pop(key, None)
                if inflight.epoch == self._epoch:
                    self._store(key, value=value, weight=weight)
            inflight.result = _InflightResult(value)
            inflight.completed = True
            inflight.event.set()
        return value

    def _store(self, key: K, *, value: V, weight: int) -> None:
        if self.max_entries == 0 or self.max_weight == 0 or weight > self.max_weight:
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._resident_weight -= previous.weight
        self._entries[key] = _Entry(value=value, weight=weight)
        self._resident_weight += weight
        while (
            len(self._entries) > self.max_entries
            or self._resident_weight > self.max_weight
        ):
            _, evicted = self._entries.popitem(last=False)
            self._resident_weight -= evicted.weight
            self._evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._epoch += 1
            self._entries.clear()
            self._inflight.clear()
            self._resident_weight = 0
        self._export_metrics()

    def _export_metrics(self) -> None:
        if self._observer is None or self._cache_name is None:
            return
        with self._lock:
            events = {
                "hit": self._hits - self._reported_hits,
                "miss": self._misses - self._reported_misses,
                "load": self._loads - self._reported_loads,
                "wait": self._waits - self._reported_waits,
                "eviction": self._evictions - self._reported_evictions,
            }
            self._reported_hits = self._hits
            self._reported_misses = self._misses
            self._reported_loads = self._loads
            self._reported_waits = self._waits
            self._reported_evictions = self._evictions
            entries = len(self._entries)
            resident_weight = self._resident_weight
        record_cache_observation(
            self._observer,
            self._cache_name,
            events,
            entries,
            resident_weight,
        )

    def stats(self) -> WeightedCacheStats:
        with self._lock:
            return WeightedCacheStats(
                entries=len(self._entries),
                resident_weight=self._resident_weight,
                hits=self._hits,
                misses=self._misses,
                loads=self._loads,
                waits=self._waits,
                evictions=self._evictions,
            )


__all__ = ["SyncWeightedSingleflightLRU", "WeightedCacheStats"]
