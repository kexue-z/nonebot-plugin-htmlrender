"""Logical package and filesystem resource sources.

Package resources are addressed by stable logical names and never exposed as
filesystem paths.  Filesystem resources retain their concrete path so callers
can opt into revalidation where appropriate.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import anyio
from anyio.to_thread import run_sync

from .budget import ResourceCacheBudget
from .config import get_resource_cache_settings

if TYPE_CHECKING:
    from importlib.abc import Traversable


def _logical_parts(name: str | PurePosixPath) -> tuple[str, ...]:
    logical = PurePosixPath(str(name))
    parts = logical.parts
    if (
        not parts
        or logical.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"Invalid logical resource name: {name!r}")
    return parts


@dataclass(frozen=True, slots=True)
class PackageResource:
    package: str
    name: str

    def __post_init__(self) -> None:
        parts = _logical_parts(self.name)
        object.__setattr__(self, "name", PurePosixPath(*parts).as_posix())

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return ("package", self.package, self.name)

    def traversable(self) -> Traversable:
        return files(self.package).joinpath(*_logical_parts(self.name))


@dataclass(frozen=True, slots=True)
class PackageResourceSource:
    package: str
    root: str = ""

    def __post_init__(self) -> None:
        if self.root:
            object.__setattr__(
                self,
                "root",
                PurePosixPath(*_logical_parts(self.root)).as_posix(),
            )

    @property
    def identity(self) -> tuple[str, str, str]:
        return ("package", self.package, self.root)

    def resource(self, name: str | PurePosixPath) -> PackageResource:
        parts = _logical_parts(name)
        logical = (
            PurePosixPath(self.root, *parts) if self.root else PurePosixPath(*parts)
        )
        return PackageResource(self.package, logical.as_posix())


@dataclass(frozen=True, slots=True)
class FilesystemResourceSource:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())

    @property
    def identity(self) -> tuple[str, str]:
        return ("filesystem", str(self.root))

    def resource(self, name: str | PurePosixPath) -> Path:
        parts = _logical_parts(name)
        candidate = self.root.joinpath(*parts).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise ValueError(f"Resource escapes filesystem root: {name!r}") from error
        return candidate


@dataclass(slots=True)
class _PackageCacheEntry:
    data: bytes
    texts: dict[tuple[str, str], str] = field(default_factory=dict)


@dataclass(slots=True)
class _PackageInflight:
    event: anyio.Event
    epoch: int
    data: bytes | None = None
    error: BaseException | None = None


class PackageResourceCache:
    """Bounded immutable package-resource cache with async singleflight."""

    def __init__(
        self,
        *,
        max_entries: int,
        max_bytes: int,
        budget: ResourceCacheBudget | None = None,
    ) -> None:
        if max_entries < 0 or max_bytes < 0:
            raise ValueError("Package resource cache limits must not be negative")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
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
        self._entries: OrderedDict[tuple[str, str, str], _PackageCacheEntry] = (
            OrderedDict()
        )
        self._resident_bytes = 0
        self._epoch = 0
        self._inflight: dict[
            tuple[int, tuple[str, str, str]],
            _PackageInflight,
        ] = {}
        self._lock = anyio.Lock()

    async def read_bytes(self, resource: PackageResource) -> bytes:
        try:
            return await self._read_bytes(resource)
        finally:
            self._budget.export_metrics()

    async def _read_bytes(self, resource: PackageResource) -> bytes:
        key = resource.cache_key
        owner = False
        async with self._lock:
            with self._budget.locked():
                cached = self._entries.get(key)
                if cached is not None:
                    self._entries.move_to_end(key)
                    self._budget.touch(self, key)
                    self._budget.record_hit()
                    return cached.data
                epoch = self._epoch
                inflight_key = (epoch, key)
                inflight = self._inflight.get(inflight_key)
                if inflight is None:
                    inflight = _PackageInflight(event=anyio.Event(), epoch=epoch)
                    self._inflight[inflight_key] = inflight
                    self._budget.record_miss()
                    owner = True
                else:
                    self._budget.record_wait()

        if not owner:
            await inflight.event.wait()
            if inflight.error is not None:
                raise inflight.error
            if inflight.data is None:
                return await self._read_bytes(resource)
            return inflight.data

        try:
            data = await run_sync(resource.traversable().read_bytes)
            self._budget.record_load()
            with anyio.CancelScope(shield=True):
                async with self._lock:
                    with self._budget.locked():
                        if self._epoch == inflight.epoch:
                            self._store(key, data)
                        current = self._inflight.pop(inflight_key, None)
                        if current is inflight:
                            inflight.data = data
                            inflight.event.set()
            return data
        except BaseException as error:
            with anyio.CancelScope(shield=True):
                async with self._lock:
                    current = self._inflight.pop(inflight_key, None)
                    if current is inflight:
                        inflight.error = error
                        inflight.event.set()
            raise

    def _store(self, key: tuple[str, str, str], data: bytes) -> None:
        size = len(data)
        if self.max_entries == 0 or self.max_bytes == 0 or size > self.max_bytes:
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._resident_bytes -= len(previous.data)
            self._budget.remove(self, key)
        self._entries[key] = _PackageCacheEntry(data=data)
        self._resident_bytes += size
        self._budget.store(self, key, size)

    def _evict_budget_entry(self, key: tuple[str, str, str]) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._resident_bytes -= len(entry.data)

    def _clear_budget_entries(self) -> None:
        self._epoch += 1
        self._entries.clear()
        self._resident_bytes = 0

    async def read_text(
        self,
        resource: PackageResource,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        data = await self.read_bytes(resource)
        key = resource.cache_key
        text_key = (encoding, errors)
        async with self._lock:
            with self._budget.locked():
                cached = self._entries.get(key)
                if cached is not None and cached.data is data:
                    text = cached.texts.get(text_key)
                    if text is None:
                        text = data.decode(encoding, errors)
                        cached.texts[text_key] = text
                    return text
        return data.decode(encoding, errors)

    async def clear(self) -> None:
        try:
            async with self._lock:
                with self._budget.locked():
                    self._clear_budget_entries()
                    self._budget.clear_participant(self)
        finally:
            self._budget.export_metrics()


@dataclass(slots=True)
class _PackageCacheState:
    cache: PackageResourceCache | None = None
    config: tuple[int, int] | None = None
    budget: ResourceCacheBudget | None = None


_PACKAGE_CACHE_STATE = _PackageCacheState()


def get_package_resource_cache() -> PackageResourceCache:
    from .cache import get_resource_cache  # noqa: PLC0415

    settings = get_resource_cache_settings()
    config = (
        settings.max_entries,
        settings.max_bytes,
    )
    budget = get_resource_cache()._budget
    if (
        _PACKAGE_CACHE_STATE.cache is None
        or _PACKAGE_CACHE_STATE.config != config
        or _PACKAGE_CACHE_STATE.budget is not budget
    ):
        _PACKAGE_CACHE_STATE.cache = PackageResourceCache(
            max_entries=config[0],
            max_bytes=config[1],
            budget=budget,
        )
        _PACKAGE_CACHE_STATE.config = config
        _PACKAGE_CACHE_STATE.budget = budget
    return _PACKAGE_CACHE_STATE.cache


async def read_package_resource_bytes(resource: PackageResource) -> bytes:
    return await get_package_resource_cache().read_bytes(resource)


async def read_package_resource_text(
    resource: PackageResource,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> str:
    return await get_package_resource_cache().read_text(
        resource,
        encoding=encoding,
        errors=errors,
    )


__all__ = [
    "FilesystemResourceSource",
    "PackageResource",
    "PackageResourceCache",
    "PackageResourceSource",
    "get_package_resource_cache",
    "read_package_resource_bytes",
    "read_package_resource_text",
]
