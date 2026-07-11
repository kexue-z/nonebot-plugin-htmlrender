"""Thread-safe weighted LRU with per-key synchronous singleflight."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading
from typing import TYPE_CHECKING, Generic, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable

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
class _Inflight(Generic[V]):
    event: threading.Event
    value: V | None = None
    error: BaseException | None = None
    completed: bool = False


class SyncWeightedSingleflightLRU(Generic[K, V]):
    """Bounded LRU that compiles different keys concurrently."""

    def __init__(self, *, max_entries: int, max_weight: int) -> None:
        if max_entries < 0 or max_weight < 0:
            raise ValueError("Weighted cache limits must not be negative")
        self.max_entries = max_entries
        self.max_weight = max_weight
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()
        self._inflight: dict[K, _Inflight[V]] = {}
        self._resident_weight = 0
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._loads = 0
        self._waits = 0
        self._evictions = 0

    def get_or_insert(self, key: K, *, weight: int, factory: Callable[[], V]) -> V:
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
                inflight = _Inflight(event=threading.Event())
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
                return self.get_or_insert(key, weight=weight, factory=factory)
            return cast("V", inflight.value)

        try:
            value = factory()
        except BaseException as error:
            with self._lock:
                current = self._inflight.pop(key, None)
                if current is inflight:
                    inflight.error = error
                    inflight.completed = True
                    inflight.event.set()
            raise

        with self._lock:
            self._loads += 1
            self._store(key, value=value, weight=weight)
            current = self._inflight.pop(key, None)
            if current is inflight:
                inflight.value = value
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
            self._entries.clear()
            self._resident_weight = 0

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
