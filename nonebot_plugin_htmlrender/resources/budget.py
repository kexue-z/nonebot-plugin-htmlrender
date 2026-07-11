"""Shared entry and byte budget for source-aware resource caches."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Hashable, Protocol


class CacheBudgetParticipant(Protocol):
    """Cache storage controlled by a shared resource budget."""

    def _evict_budget_entry(self, key: Hashable) -> None: ...

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
    participant: CacheBudgetParticipant
    key: Hashable
    size: int


class ResourceCacheBudget:
    """One process-local LRU budget shared by every resource source."""

    def __init__(self, *, max_entries: int, max_bytes: int) -> None:
        if max_entries < 0 or max_bytes < 0:
            raise ValueError("Resource cache limits must not be negative")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[tuple[int, Hashable], _BudgetEntry] = OrderedDict()
        self._participants: dict[int, CacheBudgetParticipant] = {}
        self._resident_bytes = 0
        self._hits = 0
        self._misses = 0
        self._loads = 0
        self._waits = 0
        self._evictions = 0

    @staticmethod
    def _entry_key(
        participant: CacheBudgetParticipant,
        key: Hashable,
    ) -> tuple[int, Hashable]:
        return (id(participant), key)

    def register(self, participant: CacheBudgetParticipant) -> None:
        self._participants[id(participant)] = participant

    def store(
        self,
        participant: CacheBudgetParticipant,
        key: Hashable,
        size: int,
    ) -> None:
        self.register(participant)
        budget_key = self._entry_key(participant, key)
        previous = self._entries.pop(budget_key, None)
        if previous is not None:
            self._resident_bytes -= previous.size

        if self.max_entries == 0 or self.max_bytes == 0 or size > self.max_bytes:
            participant._evict_budget_entry(key)
            return

        self._entries[budget_key] = _BudgetEntry(participant, key, size)
        self._resident_bytes += size
        while (
            len(self._entries) > self.max_entries
            or self._resident_bytes > self.max_bytes
        ):
            _, evicted = self._entries.popitem(last=False)
            self._resident_bytes -= evicted.size
            self._evictions += 1
            evicted.participant._evict_budget_entry(evicted.key)

    def touch(self, participant: CacheBudgetParticipant, key: Hashable) -> None:
        budget_key = self._entry_key(participant, key)
        if budget_key in self._entries:
            self._entries.move_to_end(budget_key)

    def remove(self, participant: CacheBudgetParticipant, key: Hashable) -> None:
        entry = self._entries.pop(self._entry_key(participant, key), None)
        if entry is not None:
            self._resident_bytes -= entry.size

    def clear_participant(self, participant: CacheBudgetParticipant) -> None:
        participant_id = id(participant)
        keys = [key for key in self._entries if key[0] == participant_id]
        for key in keys:
            self._resident_bytes -= self._entries.pop(key).size

    def clear_all(self) -> None:
        self._entries.clear()
        self._resident_bytes = 0
        for participant in tuple(self._participants.values()):
            participant._clear_budget_entries()

    def record_hit(self) -> None:
        self._hits += 1

    def record_miss(self) -> None:
        self._misses += 1

    def record_load(self) -> None:
        self._loads += 1

    def record_wait(self) -> None:
        self._waits += 1

    def stats(self) -> CacheBudgetStats:
        return CacheBudgetStats(
            entries=len(self._entries),
            resident_bytes=self._resident_bytes,
            hits=self._hits,
            misses=self._misses,
            loads=self._loads,
            waits=self._waits,
            evictions=self._evictions,
        )


__all__ = ["CacheBudgetStats", "ResourceCacheBudget"]
