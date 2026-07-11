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

from .budget import ResourceCacheBudget

if TYPE_CHECKING:
    from os import stat_result

    from .source import PackageResource


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
    epoch: int
    generation: int
    texts: dict[tuple[str, str], str] = field(default_factory=dict)


@dataclass(slots=True)
class _InflightLoad:
    event: anyio.Event
    epoch: int
    generation: int
    refresh: bool = False
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
        budget: ResourceCacheBudget | None = None,
    ) -> None:
        if max_entries < 0 or max_bytes < 0 or revalidate_seconds < 0:
            raise ValueError("Resource cache limits must not be negative")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.revalidate_seconds = revalidate_seconds
        self._budget = budget or ResourceCacheBudget(
            max_entries=max_entries,
            max_bytes=max_bytes,
        )
        if (
            self._budget.max_entries != max_entries
            or self._budget.max_bytes != max_bytes
        ):
            raise ValueError("Resource cache and shared budget limits must match")
        self._budget.register(self)
        self._entries: OrderedDict[Path, _CacheEntry] = OrderedDict()
        self._resident_bytes = 0
        self._epoch = 0
        self._generations: dict[Path, int] = {}
        self._inflight: dict[tuple[int, Path, int], _InflightLoad] = {}
        self._refresh_inflight: dict[Path, tuple[int, Path, int]] = {}
        self._lock = anyio.Lock()

    async def snapshot(
        self,
        path: str | Path,
        *,
        policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
        refresh: bool = False,
    ) -> FileSnapshot:
        resolved = await run_sync(_normalize_path, path)
        first_attempt = True

        while True:
            owner = False
            cached: _CacheEntry | None = None
            inflight: _InflightLoad | None = None
            inflight_key: tuple[int, Path, int] | None = None
            now = time.monotonic()
            async with self._lock:
                if refresh and first_attempt:
                    refresh_key = self._refresh_inflight.get(resolved)
                    if refresh_key is not None:
                        current_epoch = self._epoch
                        current_generation = self._generations.get(resolved, 0)
                        if refresh_key != (
                            current_epoch,
                            resolved,
                            current_generation,
                        ):
                            self._refresh_inflight.pop(resolved, None)
                            existing_refresh = None
                        else:
                            existing_refresh = self._inflight.get(refresh_key)
                        if existing_refresh is not None:
                            inflight = existing_refresh
                            self._budget.record_wait()
                            owner = False
                            first_attempt = False
                            existing = inflight
                            cached = None
                            inflight_key = refresh_key
                        else:
                            self._refresh_inflight.pop(resolved, None)
                            existing = None
                    else:
                        existing = None

                    if existing is None:
                        generation = self._generations.get(resolved, 0) + 1
                        self._generations[resolved] = generation
                        epoch = self._epoch
                        inflight_key = (epoch, resolved, generation)
                        inflight = _InflightLoad(
                            event=anyio.Event(),
                            epoch=epoch,
                            generation=generation,
                            refresh=True,
                        )
                        self._inflight[inflight_key] = inflight
                        self._refresh_inflight[resolved] = inflight_key
                        self._budget.record_miss()
                        owner = True
                        cached = None
                        entry = self._entries.pop(resolved, None)
                        if entry is not None:
                            self._resident_bytes -= len(entry.snapshot.data)
                            self._budget.remove(self, resolved)
                    first_attempt = False
                else:
                    epoch = self._epoch
                    generation = self._generations.get(resolved, 0)
                    inflight_key = (epoch, resolved, generation)
                    cached = self._entries.get(resolved)
                    if cached is not None and (
                        cached.epoch != epoch or cached.generation != generation
                    ):
                        cached = None

                    if cached is not None and (
                        policy is FileCachePolicy.IMMUTABLE
                        or now - cached.checked_at < self.revalidate_seconds
                    ):
                        self._entries.move_to_end(resolved)
                        self._budget.touch(self, resolved)
                        self._budget.record_hit()
                        return cached.snapshot

                    existing = self._inflight.get(inflight_key)
                    if existing is None:
                        inflight = _InflightLoad(
                            event=anyio.Event(),
                            epoch=epoch,
                            generation=generation,
                        )
                        self._inflight[inflight_key] = inflight
                        self._budget.record_miss()
                        owner = True
                    else:
                        inflight = existing
                        self._budget.record_wait()

            if inflight is None or inflight_key is None:
                raise RuntimeError("Resource cache load state was not initialized")

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
                    refresh=inflight.refresh,
                )
                async with self._lock:
                    if loaded:
                        self._budget.record_load()
                    if (
                        self._epoch == inflight.epoch
                        and self._generations.get(resolved, 0) == inflight.generation
                    ):
                        self._store(
                            snapshot,
                            checked_at=time.monotonic(),
                            epoch=inflight.epoch,
                            generation=inflight.generation,
                        )
                    current = self._inflight.pop(inflight_key, None)
                    if current is inflight:
                        if self._refresh_inflight.get(resolved) == inflight_key:
                            self._refresh_inflight.pop(resolved, None)
                        inflight.snapshot = snapshot
                        inflight.event.set()
                return snapshot
            except BaseException as error:
                with anyio.CancelScope(shield=True):
                    async with self._lock:
                        current = self._inflight.pop(inflight_key, None)
                        if current is inflight:
                            if self._refresh_inflight.get(resolved) == inflight_key:
                                self._refresh_inflight.pop(resolved, None)
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

    def _store(
        self,
        snapshot: FileSnapshot,
        *,
        checked_at: float,
        epoch: int,
        generation: int,
    ) -> None:
        previous = self._entries.pop(snapshot.path, None)
        if previous is not None:
            self._resident_bytes -= len(previous.snapshot.data)
            self._budget.remove(self, snapshot.path)

        size = len(snapshot.data)
        if self.max_entries == 0 or self.max_bytes == 0 or size > self.max_bytes:
            return

        self._entries[snapshot.path] = _CacheEntry(
            snapshot=snapshot,
            checked_at=checked_at,
            epoch=epoch,
            generation=generation,
        )
        self._resident_bytes += size
        self._budget.store(self, snapshot.path, size)

    def _evict_budget_entry(self, key: object) -> None:
        if not isinstance(key, Path):
            return
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._resident_bytes -= len(entry.snapshot.data)

    def _clear_budget_entries(self) -> None:
        self._epoch += 1
        self._generations.clear()
        self._refresh_inflight.clear()
        self._entries.clear()
        self._resident_bytes = 0

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
            self._generations[resolved] = self._generations.get(resolved, 0) + 1
            self._refresh_inflight.pop(resolved, None)
            entry = self._entries.pop(resolved, None)
            if entry is not None:
                self._resident_bytes -= len(entry.snapshot.data)
                self._budget.remove(self, resolved)

    async def clear(self) -> None:
        async with self._lock:
            self._budget.clear_all()

    async def stats(self) -> ResourceCacheStats:
        async with self._lock:
            stats = self._budget.stats()
            return ResourceCacheStats(
                entries=stats.entries,
                resident_bytes=stats.resident_bytes,
                hits=stats.hits,
                misses=stats.misses,
                loads=stats.loads,
                waits=stats.waits,
                evictions=stats.evictions,
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
    path: str | Path | PackageResource,
    *,
    policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
    refresh: bool = False,
) -> bytes:
    from .source import (  # noqa: PLC0415
        PackageResource,
        get_package_resource_cache,
        read_package_resource_bytes,
    )

    if isinstance(path, PackageResource):
        if refresh:
            await get_package_resource_cache().clear()
        return await read_package_resource_bytes(path)
    return await get_resource_cache().read_bytes(
        path,
        policy=policy,
        refresh=refresh,
    )


async def read_resource_text(
    path: str | Path | PackageResource,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
    policy: FileCachePolicy = FileCachePolicy.REVALIDATE,
    refresh: bool = False,
) -> str:
    from .source import (  # noqa: PLC0415
        PackageResource,
        get_package_resource_cache,
        read_package_resource_text,
    )

    if isinstance(path, PackageResource):
        if refresh:
            await get_package_resource_cache().clear()
        return await read_package_resource_text(
            path,
            encoding=encoding,
            errors=errors,
        )
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
