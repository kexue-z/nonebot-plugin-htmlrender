"""Shared entry and byte budget for source-aware resource caches."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import threading
from typing import TYPE_CHECKING, Hashable, Protocol, TypeVar

from nonebot_plugin_htmlrender.utils.telemetry import record_cache_metrics

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

K = TypeVar("K", bound=Hashable, contravariant=True)


class CacheBudgetParticipant(Protocol[K]):
    """Cache storage controlled by a shared resource budget."""

    def _evict_budget_entry(self, key: K) -> None: ...

    def _clear_budget_entries(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CacheBudgetStats:
    entries: int
    resident_bytes: int
    hits: int
    misses: int
    loads: int
    waits: int
    evictions: int


@dataclass(frozen=True, slots=True)
class _BudgetEntry:
    evict: Callable[[], None]
    size: int


class ResourceCacheBudget:
    """One process-local LRU budget shared by every resource source."""

    def __init__(self, *, max_entries: int, max_bytes: int) -> None:
        if max_entries < 0 or max_bytes < 0:
            raise ValueError("Resource cache limits must not be negative")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[tuple[int, Hashable], _BudgetEntry] = OrderedDict()
        self._participants: dict[int, Callable[[], None]] = {}
        self._lock = threading.RLock()
        self._resident_bytes = 0
        self._hits = 0
        self._misses = 0
        self._loads = 0
        self._waits = 0
        self._evictions = 0
        self._reported_hits = 0
        self._reported_misses = 0
        self._reported_loads = 0
        self._reported_waits = 0
        self._reported_evictions = 0

    @staticmethod
    def _entry_key(
        participant: CacheBudgetParticipant[K],
        key: K,
    ) -> tuple[int, Hashable]:
        return (id(participant), key)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize budget state and every participant's resident entries."""

        with self._lock:
            yield

    def register(self, participant: CacheBudgetParticipant[K]) -> None:
        with self._lock:
            self._participants[id(participant)] = participant._clear_budget_entries

    def store(
        self,
        participant: CacheBudgetParticipant[K],
        key: K,
        size: int,
    ) -> None:
        with self._lock:
            self.register(participant)
            budget_key = self._entry_key(participant, key)
            previous = self._entries.pop(budget_key, None)
            if previous is not None:
                self._resident_bytes -= previous.size

            if self.max_entries == 0 or self.max_bytes == 0 or size > self.max_bytes:
                participant._evict_budget_entry(key)
                return

            self._entries[budget_key] = _BudgetEntry(
                evict=lambda: participant._evict_budget_entry(key),
                size=size,
            )
            self._resident_bytes += size
            while (
                len(self._entries) > self.max_entries
                or self._resident_bytes > self.max_bytes
            ):
                _, evicted = self._entries.popitem(last=False)
                self._resident_bytes -= evicted.size
                self._evictions += 1
                evicted.evict()

    def touch(self, participant: CacheBudgetParticipant[K], key: K) -> None:
        with self._lock:
            budget_key = self._entry_key(participant, key)
            if budget_key in self._entries:
                self._entries.move_to_end(budget_key)

    def remove(self, participant: CacheBudgetParticipant[K], key: K) -> None:
        with self._lock:
            entry = self._entries.pop(self._entry_key(participant, key), None)
            if entry is not None:
                self._resident_bytes -= entry.size

    def clear_participant(self, participant: CacheBudgetParticipant[K]) -> None:
        with self._lock:
            participant_id = id(participant)
            keys = [key for key in self._entries if key[0] == participant_id]
            for key in keys:
                self._resident_bytes -= self._entries.pop(key).size

    def clear_all(self) -> None:
        with self._lock:
            self._entries.clear()
            self._resident_bytes = 0
            for clear in tuple(self._participants.values()):
                clear()

    def record_hit(self) -> None:
        with self._lock:
            self._hits += 1

    def record_miss(self) -> None:
        with self._lock:
            self._misses += 1

    def record_load(self) -> None:
        with self._lock:
            self._loads += 1

    def record_wait(self) -> None:
        with self._lock:
            self._waits += 1

    def stats(self) -> CacheBudgetStats:
        with self._lock:
            return CacheBudgetStats(
                entries=len(self._entries),
                resident_bytes=self._resident_bytes,
                hits=self._hits,
                misses=self._misses,
                loads=self._loads,
                waits=self._waits,
                evictions=self._evictions,
            )

    def export_metrics(self) -> None:
        """Drain event deltas and export a state snapshot outside the budget lock."""

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
            resident_bytes = self._resident_bytes
        record_cache_metrics("resource", events, entries, resident_bytes)


__all__ = ["CacheBudgetStats", "ResourceCacheBudget"]
