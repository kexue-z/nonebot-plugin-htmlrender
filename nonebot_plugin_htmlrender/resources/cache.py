"""Backend-neutral cache for immutable and user-provided file resources."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
import os
from pathlib import Path
import time
from typing import TYPE_CHECKING

import anyio
from anyio.to_thread import run_sync

from nonebot_plugin_htmlrender.config import plugin_config

if TYPE_CHECKING:
    from os import stat_result


class FileCachePolicy(str, Enum):
    """File validation policy used by :class:`FileResourceCache`."""

    IMMUTABLE = "immutable"
    REVALIDATE = "revalidate"


@dataclass(frozen=True, slots=True)
class FileRevision:
    """Filesystem identity used to detect content replacement or mutation."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, stat: stat_result) -> FileRevision:
        return cls(
            device=stat.st_dev,
            inode=stat.st_ino,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            ctime_ns=stat.st_ctime_ns,
        )


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    """One internally consistent snapshot of a file."""

    path: Path
    revision: FileRevision
    data: bytes


@dataclass(frozen=True, slots=True)
class ResourceCacheStats:
    entries: int
    resident_bytes: int
    hits: int
    misses: int
    loads: int
    waits: int
    evictions: int


@dataclass(slots=True)
class _CacheEntry:
    snapshot: FileSnapshot
    checked_at: float
    texts: dict[tuple[str, str], str] = field(default_factory=dict)


@dataclass(slots=True)
class _InflightLoad:
    event: anyio.Event
    snapshot: FileSnapshot | None = None
    error: BaseException | None = None


def _normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _stat_revision(path: Path) -> FileRevision:
    return FileRevision.from_stat(path.stat())


def _read_consistent_snapshot(path: Path) -> FileSnapshot:
    for _ in range(3):
        with path.open("rb") as file:
            before = FileRevision.from_stat(os.fstat(file.fileno()))
            data = file.read()
            after = FileRevision.from_stat(os.fstat(file.fileno()))
        if before == after and len(data) == after.size:
            return FileSnapshot(path=path, revision=after, data=data)
    raise RuntimeError(f"File changed repeatedly while reading: {path}")


class FileResourceCache:
    """Bounded byte-weighted LRU with revalidation and concurrent load deduping."""

    def __init__(
        self,
        *,
        max_entries: int,
        max_bytes: int,
        revalidate_seconds: float,
    ) -> None:
        if max_entries < 0 or max_bytes < 0 or revalidate_seconds < 0:
            raise ValueError("Resource cache limits must not be negative")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.revalidate_seconds = revalidate_seconds
        self._entries: OrderedDict[Path, _CacheEntry] = OrderedDict()
        self._resident_bytes = 0
        self._inflight: dict[tuple[Path, bool], _InflightLoad] = {}
        self._lock = anyio.Lock()
        self._hits = 0
        self._misses = 0
        self._loads = 0
        self._waits = 0
        self._evictions = 0

    async def snapshot(
        self,
        path: str | Path,
        *,
        policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
        refresh: bool = False,
    ) -> FileSnapshot:
        resolved = await run_sync(_normalize_path, path)
        inflight_key = (resolved, refresh)

        while True:
            owner = False
            inflight: _InflightLoad
            now = time.monotonic()
            async with self._lock:
                cached = self._entries.get(resolved)
                if (
                    cached is not None
                    and not refresh
                    and (
                        policy is FileCachePolicy.IMMUTABLE
                        or now - cached.checked_at < self.revalidate_seconds
                    )
                ):
                    self._entries.move_to_end(resolved)
                    self._hits += 1
                    return cached.snapshot

                existing = self._inflight.get(inflight_key)
                if existing is None:
                    inflight = _InflightLoad(event=anyio.Event())
                    self._inflight[inflight_key] = inflight
                    self._misses += 1
                    owner = True
                else:
                    inflight = existing
                    self._waits += 1

            if not owner:
                await inflight.event.wait()
                if inflight.error is not None:
                    raise inflight.error
                if inflight.snapshot is not None:
                    return inflight.snapshot
                continue

            try:
                snapshot, loaded = await self._load(
                    resolved,
                    cached=cached,
                    refresh=refresh,
                )
                async with self._lock:
                    if loaded:
                        self._loads += 1
                    self._store(snapshot, checked_at=time.monotonic())
                    current = self._inflight.pop(inflight_key, None)
                    if current is inflight:
                        inflight.snapshot = snapshot
                        inflight.event.set()
                return snapshot
            except BaseException as error:
                with anyio.CancelScope(shield=True):
                    async with self._lock:
                        current = self._inflight.pop(inflight_key, None)
                        if current is inflight:
                            if isinstance(error, Exception):
                                inflight.error = error
                            inflight.event.set()
                raise

    async def _load(
        self,
        path: Path,
        *,
        cached: _CacheEntry | None,
        refresh: bool,
    ) -> tuple[FileSnapshot, bool]:
        if cached is not None and not refresh:
            revision = await run_sync(_stat_revision, path)
            if revision == cached.snapshot.revision:
                return cached.snapshot, False
        snapshot = await run_sync(_read_consistent_snapshot, path)
        return snapshot, True

    def _store(self, snapshot: FileSnapshot, *, checked_at: float) -> None:
        previous = self._entries.pop(snapshot.path, None)
        if previous is not None:
            self._resident_bytes -= len(previous.snapshot.data)

        size = len(snapshot.data)
        if self.max_entries == 0 or self.max_bytes == 0 or size > self.max_bytes:
            return

        self._entries[snapshot.path] = _CacheEntry(
            snapshot=snapshot,
            checked_at=checked_at,
        )
        self._resident_bytes += size
        while (
            len(self._entries) > self.max_entries
            or self._resident_bytes > self.max_bytes
        ):
            _, evicted = self._entries.popitem(last=False)
            self._resident_bytes -= len(evicted.snapshot.data)
            self._evictions += 1

    async def read_bytes(
        self,
        path: str | Path,
        *,
        policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
        refresh: bool = False,
    ) -> bytes:
        return (await self.snapshot(path, policy=policy, refresh=refresh)).data

    async def read_text(
        self,
        path: str | Path,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
        policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
        refresh: bool = False,
    ) -> str:
        snapshot = await self.snapshot(path, policy=policy, refresh=refresh)
        text_key = (encoding, errors)
        async with self._lock:
            cached = self._entries.get(snapshot.path)
            if cached is not None and cached.snapshot.revision == snapshot.revision:
                text = cached.texts.get(text_key)
                if text is None:
                    text = snapshot.data.decode(encoding, errors)
                    cached.texts[text_key] = text
                return text
        return snapshot.data.decode(encoding, errors)

    async def invalidate(self, path: str | Path) -> None:
        resolved = await run_sync(_normalize_path, path)
        async with self._lock:
            entry = self._entries.pop(resolved, None)
            if entry is not None:
                self._resident_bytes -= len(entry.snapshot.data)

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()
            self._resident_bytes = 0

    async def stats(self) -> ResourceCacheStats:
        async with self._lock:
            return ResourceCacheStats(
                entries=len(self._entries),
                resident_bytes=self._resident_bytes,
                hits=self._hits,
                misses=self._misses,
                loads=self._loads,
                waits=self._waits,
                evictions=self._evictions,
            )


@dataclass(slots=True)
class _ResourceCacheState:
    cache: FileResourceCache | None = None
    config: tuple[int, int, float] | None = None


_state = _ResourceCacheState()


def get_resource_cache() -> FileResourceCache:
    config = (
        plugin_config.render_resource_cache_max_entries,
        plugin_config.render_resource_cache_max_bytes,
        plugin_config.render_resource_cache_revalidate_seconds,
    )
    if _state.cache is None or _state.config != config:
        _state.cache = FileResourceCache(
            max_entries=config[0],
            max_bytes=config[1],
            revalidate_seconds=config[2],
        )
        _state.config = config
    return _state.cache


async def read_resource_bytes(
    path: str | Path,
    *,
    policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
    refresh: bool = False,
) -> bytes:
    return await get_resource_cache().read_bytes(
        path,
        policy=policy,
        refresh=refresh,
    )


async def read_resource_text(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
    policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
    refresh: bool = False,
) -> str:
    return await get_resource_cache().read_text(
        path,
        encoding=encoding,
        errors=errors,
        policy=policy,
        refresh=refresh,
    )


__all__ = (
    "FileCachePolicy",
    "FileResourceCache",
    "FileRevision",
    "FileSnapshot",
    "ResourceCacheStats",
    "get_resource_cache",
    "read_resource_bytes",
    "read_resource_text",
)
