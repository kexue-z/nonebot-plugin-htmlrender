from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
import mimetypes
import os
from pathlib import Path, PurePosixPath
import time
from typing import TYPE_CHECKING, TypeVar, final
from urllib.error import HTTPError
from urllib.request import urlopen

import anyio
from anyio.to_thread import run_sync

from nonebot_plugin_htmlrender.resources.models import (
    FileResourceRef,
    InlineResourceRef,
    PackageResourceRef,
    RemoteResourceRef,
    ResourceContent,
    ResourceRef,
    ResourceRevision,
)
from nonebot_plugin_htmlrender.resources.path_guard import validate_local_access

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from nonebot_plugin_htmlrender.resources.config import ResourceCacheSettings
    from nonebot_plugin_htmlrender.resources.observation import CacheObserver
    from nonebot_plugin_htmlrender.resources.ports import ResourceReader, WorkerExecutor

from nonebot_plugin_htmlrender.resources.errors import (
    ResourceAccessDenied,
    ResourceNotFound,
    ResourceResolutionError,
    ResourceSizeExceeded,
)

R = TypeVar("R")


@final
class AnyioWorkerExecutor:
    async def run_sync(self, function: Callable[..., R], *args: object) -> R:
        return await run_sync(function, *args)


@final
class ConfiguredLocalAccessPolicy:
    def __init__(self, *, allowed_roots: Sequence[Path], allow_any: bool) -> None:
        self._allowed_roots = tuple(
            path.expanduser().resolve() for path in allowed_roots
        )
        self._allow_any = allow_any

    def authorize(self, path: Path) -> Path:
        try:
            return validate_local_access(
                path,
                allowed_roots=self._allowed_roots,
                allow_any=self._allow_any,
                on_deny=ResourceAccessDenied,
            )
        except ResourceResolutionError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            raise ResourceResolutionError(
                f"Could not normalize local resource path: {error}"
            ) from error


def _file_revision(path: Path) -> ResourceRevision:
    stat = path.stat()
    return ResourceRevision(
        f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
    )


def _read_bounded(read: Callable[[int], bytes], limit: int, label: str) -> bytes:
    data = read(-1 if limit == 0 else limit + 1)
    if limit > 0 and len(data) > limit:
        raise ResourceSizeExceeded(
            f"Resource {label} exceeds the configured {limit}-byte read limit."
        )
    return data


def _read_file(path: Path, max_resource_bytes: int) -> ResourceContent:
    for _ in range(3):
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if max_resource_bytes > 0 and before.st_size > max_resource_bytes:
                raise ResourceSizeExceeded(
                    f"Resource {path} exceeds the configured "
                    f"{max_resource_bytes}-byte read limit."
                )
            data = _read_bounded(stream.read, max_resource_bytes, str(path))
            after = os.fstat(stream.fileno())
        before_revision = ResourceRevision(
            f"{before.st_dev}:{before.st_ino}:{before.st_size}:{before.st_mtime_ns}:{before.st_ctime_ns}"
        )
        after_revision = ResourceRevision(
            f"{after.st_dev}:{after.st_ino}:{after.st_size}:{after.st_mtime_ns}:{after.st_ctime_ns}"
        )
        if before_revision == after_revision and len(data) == after.st_size:
            return ResourceContent(
                data,
                mimetypes.guess_type(path.name)[0],
                after_revision,
            )
    raise RuntimeError(f"File changed repeatedly while reading: {path}")


def _read_package(
    reference: PackageResourceRef,
    max_resource_bytes: int,
) -> ResourceContent:
    traversable = files(reference.package).joinpath(
        *PurePosixPath(reference.name).parts
    )
    with traversable.open("rb") as stream:
        data = _read_bounded(
            stream.read,
            max_resource_bytes,
            f"{reference.package}:{reference.name}",
        )
    return ResourceContent(
        data,
        mimetypes.guess_type(reference.name)[0],
        ResourceRevision(f"package:{reference.package}:{reference.name}"),
    )


def _read_remote(
    reference: RemoteResourceRef,
    max_resource_bytes: int,
) -> ResourceContent:
    with urlopen(reference.url, timeout=30) as response:  # noqa: S310 -- explicit opt-in ref
        content_length = response.headers.get("Content-Length")
        if (
            max_resource_bytes > 0
            and content_length is not None
            and content_length.isdigit()
            and int(content_length) > max_resource_bytes
        ):
            raise ResourceSizeExceeded(
                f"Resource {reference.url} exceeds the configured "
                f"{max_resource_bytes}-byte read limit."
            )
        data = _read_bounded(response.read, max_resource_bytes, reference.url)
        media_type = response.headers.get_content_type()
        etag = response.headers.get("ETag")
        modified = response.headers.get("Last-Modified")
    revision = ResourceRevision(etag or modified) if etag or modified else None
    return ResourceContent(data, media_type, revision)


@final
class CompositeResourceReader:
    """Dispatch concrete resource refs to source-specific adapters."""

    def __init__(
        self,
        worker: WorkerExecutor,
        *,
        max_resource_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if max_resource_bytes < 0:
            raise ValueError("Resource read limit must not be negative.")
        self._worker = worker
        self._max_resource_bytes = max_resource_bytes

    async def read(self, reference: ResourceRef) -> ResourceContent:
        try:
            if isinstance(reference, FileResourceRef):
                return await self._worker.run_sync(
                    _read_file,
                    reference.path,
                    self._max_resource_bytes,
                )
            if isinstance(reference, PackageResourceRef):
                return await self._worker.run_sync(
                    _read_package,
                    reference,
                    self._max_resource_bytes,
                )
            if isinstance(reference, RemoteResourceRef):
                return await self._worker.run_sync(
                    _read_remote,
                    reference,
                    self._max_resource_bytes,
                )
            if isinstance(reference, InlineResourceRef):
                if (
                    self._max_resource_bytes > 0
                    and len(reference.data) > self._max_resource_bytes
                ):
                    raise ResourceSizeExceeded(
                        "Inline resource exceeds the configured "
                        f"{self._max_resource_bytes}-byte read limit."
                    )
                return ResourceContent(
                    reference.data,
                    reference.media_type,
                    ResourceRevision(sha256(reference.data).hexdigest()),
                )
        except ResourceResolutionError:
            raise
        except FileNotFoundError as error:
            raise ResourceNotFound(str(error)) from error
        except PermissionError as error:
            raise ResourceAccessDenied(str(error)) from error
        except HTTPError as error:
            remote_url = (
                reference.url
                if isinstance(reference, RemoteResourceRef)
                else repr(reference)
            )
            if error.code == 404:
                raise ResourceNotFound(
                    f"Remote resource was not found: {remote_url}"
                ) from error
            raise ResourceResolutionError(
                f"Remote resource request failed with HTTP {error.code}: {remote_url}"
            ) from error
        except OSError as error:
            raise ResourceResolutionError(str(error)) from error
        except Exception as error:
            raise ResourceResolutionError(
                f"Could not read resource {reference!r}: {error}"
            ) from error
        raise ResourceResolutionError(f"Unsupported resource reference: {reference!r}")

    async def revision(self, reference: ResourceRef) -> ResourceRevision | None:
        if isinstance(reference, FileResourceRef):
            try:
                return await self._worker.run_sync(_file_revision, reference.path)
            except FileNotFoundError as error:
                raise ResourceNotFound(str(error)) from error
            except PermissionError as error:
                raise ResourceAccessDenied(str(error)) from error
            except OSError as error:
                raise ResourceResolutionError(str(error)) from error
            except Exception as error:
                raise ResourceResolutionError(
                    f"Could not inspect resource {reference!r}: {error}"
                ) from error
        if isinstance(reference, PackageResourceRef):
            return ResourceRevision(f"package:{reference.package}:{reference.name}")
        if isinstance(reference, InlineResourceRef):
            return ResourceRevision(sha256(reference.data).hexdigest())
        return None

    async def invalidate(self, reference: ResourceRef) -> None:
        del reference

    async def clear(self) -> None:
        return None


@dataclass(slots=True)
class _Inflight:
    event: anyio.Event
    content: ResourceContent | None = None
    error: BaseException | None = None


@final
class SingleflightResourceReader:
    """Deduplicate concurrent reads without retaining completed content."""

    def __init__(self, inner: ResourceReader) -> None:
        self._inner = inner
        self._inflight: dict[tuple[int, int, object], _Inflight] = {}
        self._epoch = 0
        self._generations: dict[object, int] = {}
        self._lock = anyio.Lock()

    async def read(self, reference: ResourceRef) -> ResourceContent:
        key = reference.cache_key
        async with self._lock:
            inflight_key = (
                self._epoch,
                self._generations.get(key, 0),
                key,
            )
            inflight = self._inflight.get(inflight_key)
            owner = inflight is None
            if inflight is None:
                inflight = _Inflight(anyio.Event())
                self._inflight[inflight_key] = inflight
        if not owner:
            await inflight.event.wait()
            if inflight.error is not None:
                raise inflight.error
            if inflight.content is None:
                return await self.read(reference)
            return inflight.content
        try:
            content = await self._inner.read(reference)
            with anyio.CancelScope(shield=True):
                async with self._lock:
                    self._inflight.pop(inflight_key, None)
                    inflight.content = content
                    inflight.event.set()
            return content
        except BaseException as error:
            with anyio.CancelScope(shield=True):
                async with self._lock:
                    self._inflight.pop(inflight_key, None)
                    inflight.error = error
                    inflight.event.set()
            raise

    async def revision(self, reference: ResourceRef) -> ResourceRevision | None:
        return await self._inner.revision(reference)

    async def invalidate(self, reference: ResourceRef) -> None:
        key = reference.cache_key
        async with self._lock:
            self._generations[key] = self._generations.get(key, 0) + 1
        await self._inner.invalidate(reference)

    async def clear(self) -> None:
        async with self._lock:
            self._epoch += 1
            self._generations.clear()
        await self._inner.clear()


@dataclass(slots=True)
class _CacheEntry:
    content: ResourceContent
    checked_at: float
    epoch: int
    generation: int


@final
class CachingResourceReader:
    """Bounded, byte-weighted LRU decorator with source revalidation."""

    def __init__(
        self,
        inner: ResourceReader,
        *,
        settings: ResourceCacheSettings,
        observer: CacheObserver,
    ) -> None:
        self._inner = inner
        self._settings = settings
        self._observer = observer
        self._entries: OrderedDict[object, _CacheEntry] = OrderedDict()
        self._resident_bytes = 0
        self._epoch = 0
        self._generations: dict[object, int] = {}
        self._lock = anyio.Lock()
        self._hits = 0
        self._misses = 0
        self._loads = 0
        self._evictions = 0

    def _record(self, events: dict[str, int]) -> None:
        try:
            self._observer.record(
                "resource",
                events,
                len(self._entries),
                self._resident_bytes,
            )
        except Exception:
            return

    async def read(self, reference: ResourceRef) -> ResourceContent:
        key = reference.cache_key
        now = time.monotonic()
        async with self._lock:
            entry = self._entries.get(key)
            epoch = self._epoch
            generation = self._generations.get(key, 0)
            if (
                entry is not None
                and entry.epoch == epoch
                and entry.generation == generation
                and now - entry.checked_at < self._settings.revalidate_seconds
            ):
                self._entries.move_to_end(key)
                self._hits += 1
                self._record({"hit": 1})
                return entry.content
        if entry is not None:
            stale = entry
            current = await self._inner.revision(reference)
            if current is not None and current == stale.content.revision:
                async with self._lock:
                    live = self._entries.get(key)
                    if (
                        live is not None
                        and live is stale
                        and live.epoch == epoch
                        and live.generation == generation
                    ):
                        live.checked_at = now
                        self._entries.move_to_end(key)
                        self._hits += 1
                        self._record({"hit": 1})
                        return live.content
        self._misses += 1
        content = await self._inner.read(reference)
        self._loads += 1
        async with self._lock:
            if self._epoch == epoch and self._generations.get(key, 0) == generation:
                self._store(key, content, epoch, generation)
            self._record({"miss": 1, "load": 1})
        return content

    def _store(
        self,
        key: object,
        content: ResourceContent,
        epoch: int,
        generation: int,
    ) -> None:
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._resident_bytes -= len(previous.content.data)
        size = len(content.data)
        if (
            self._settings.max_entries == 0
            or self._settings.max_bytes == 0
            or size > self._settings.max_bytes
        ):
            return
        self._entries[key] = _CacheEntry(content, time.monotonic(), epoch, generation)
        self._resident_bytes += size
        while (
            len(self._entries) > self._settings.max_entries
            or self._resident_bytes > self._settings.max_bytes
        ):
            _, evicted = self._entries.popitem(last=False)
            self._resident_bytes -= len(evicted.content.data)
            self._evictions += 1

    async def revision(self, reference: ResourceRef) -> ResourceRevision | None:
        return await self._inner.revision(reference)

    async def invalidate(self, reference: ResourceRef) -> None:
        key = reference.cache_key
        async with self._lock:
            self._generations[key] = self._generations.get(key, 0) + 1
            entry = self._entries.pop(key, None)
            if entry is not None:
                self._resident_bytes -= len(entry.content.data)
        await self._inner.invalidate(reference)

    async def clear(self) -> None:
        async with self._lock:
            self._epoch += 1
            self._entries.clear()
            self._resident_bytes = 0
            self._generations.clear()
            self._record({})
        await self._inner.clear()


def build_resource_reader(
    settings: ResourceCacheSettings,
    observer: CacheObserver,
    worker: WorkerExecutor,
) -> CachingResourceReader:
    direct = CompositeResourceReader(
        worker,
        max_resource_bytes=settings.max_resource_bytes,
    )
    singleflight = SingleflightResourceReader(direct)
    return CachingResourceReader(singleflight, settings=settings, observer=observer)


__all__ = [
    "AnyioWorkerExecutor",
    "CachingResourceReader",
    "CompositeResourceReader",
    "ConfiguredLocalAccessPolicy",
    "SingleflightResourceReader",
    "build_resource_reader",
]
