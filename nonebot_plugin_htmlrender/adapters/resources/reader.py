from __future__ import annotations

from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from importlib.resources import files
import mimetypes
import os
from pathlib import Path, PurePosixPath
import time
from typing import TYPE_CHECKING, ParamSpec, TypeVar, final

import anyio
from anyio.to_thread import run_sync

from nonebot_plugin_htmlrender.resources.config import RemoteAccessSettings
from nonebot_plugin_htmlrender.resources.errors import (
    ResourceAccessDenied,
    ResourceNotFound,
    ResourceResolutionError,
    ResourceSizeExceeded,
)
from nonebot_plugin_htmlrender.resources.models import (
    FileResourceRef,
    InlineResourceRef,
    NotModified,
    PackageResourceRef,
    RemoteResourceRef,
    ResourceContent,
    ResourceRef,
    ResourceRevision,
)
from nonebot_plugin_htmlrender.resources.path_guard import validate_local_access

from .remote import (
    ConfiguredRemoteAccessPolicy,
    RemoteTransportExecutor,
    read_bounded,
    read_remote,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

    from nonebot_plugin_htmlrender.resources.config import ResourceCacheSettings
    from nonebot_plugin_htmlrender.resources.observation import CacheObserver
    from nonebot_plugin_htmlrender.resources.ports import (
        RemoteAccessPolicy,
        ResourceReader,
        WorkerExecutor,
    )

R = TypeVar("R")
P = ParamSpec("P")


@final
class AnyioWorkerExecutor:
    async def run_sync(
        self,
        function: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        return await run_sync(partial(function, *args, **kwargs))


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
                "Could not normalize local resource path.",
                source=error,
            ) from error


def _file_revision(path: Path) -> ResourceRevision:
    stat = path.stat()
    return ResourceRevision(
        f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
    )


def _read_file(path: Path, max_resource_bytes: int) -> ResourceContent:
    for _ in range(3):
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if max_resource_bytes > 0 and before.st_size > max_resource_bytes:
                raise ResourceSizeExceeded(
                    f"Resource {path} exceeds the configured "
                    f"{max_resource_bytes}-byte read limit."
                )
            data = read_bounded(stream.read, max_resource_bytes, str(path))
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
        data = read_bounded(
            stream.read,
            max_resource_bytes,
            f"{reference.package}:{reference.name}",
        )
    return ResourceContent(
        data,
        mimetypes.guess_type(reference.name)[0],
        ResourceRevision(f"package:{reference.package}:{reference.name}"),
    )


@final
class CompositeResourceReader:
    """Dispatch concrete resource refs to source-specific adapters."""

    def __init__(
        self,
        worker: WorkerExecutor,
        *,
        remote_transport: RemoteTransportExecutor,
        max_resource_bytes: int = 64 * 1024 * 1024,
        remote_access: RemoteAccessPolicy | None = None,
        remote_timeout_seconds: float = 30.0,
    ) -> None:
        if max_resource_bytes < 0:
            raise ValueError("Resource read limit must not be negative.")
        self._worker = worker
        self._max_resource_bytes = max_resource_bytes
        self._remote_access = remote_access or ConfiguredRemoteAccessPolicy()
        self._remote_transport = remote_transport
        self._remote_timeout_seconds = remote_timeout_seconds

    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent:
        del refresh
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
                # Remote transport owns its own bounded, cancellable executor;
                # it must not borrow the shared completion-bound worker pool.
                return await read_remote(
                    reference,
                    policy=self._remote_access,
                    transport=self._remote_transport,
                    max_resource_bytes=self._max_resource_bytes,
                    request_timeout_seconds=self._remote_timeout_seconds,
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
                    ResourceRevision(reference.digest),
                )
        except ResourceResolutionError:
            raise
        except FileNotFoundError as error:
            raise ResourceNotFound("Resource was not found.", source=error) from error
        except PermissionError as error:
            raise ResourceAccessDenied(
                "Resource access was denied.", source=error
            ) from error
        except OSError as error:
            raise ResourceResolutionError(
                "Resource read failed.", source=error
            ) from error
        except Exception as error:
            raise ResourceResolutionError(
                f"Could not read resource {reference!r}.",
                source=error,
            ) from error
        raise ResourceResolutionError(f"Unsupported resource reference: {reference!r}")

    async def read_conditional(
        self,
        reference: ResourceRef,
        revision: ResourceRevision,
    ) -> ResourceContent | NotModified:
        if isinstance(reference, RemoteResourceRef):
            try:
                return await read_remote(
                    reference,
                    policy=self._remote_access,
                    transport=self._remote_transport,
                    max_resource_bytes=self._max_resource_bytes,
                    request_timeout_seconds=self._remote_timeout_seconds,
                    conditional_revision=revision,
                )
            except ResourceResolutionError:
                raise
            except OSError as error:
                raise ResourceResolutionError(
                    "Conditional resource read failed.", source=error
                ) from error
            except Exception as error:
                raise ResourceResolutionError(
                    f"Could not read resource {reference!r}.",
                    source=error,
                ) from error
        current = await self.revision(reference)
        if current is not None and current == revision:
            return NotModified(revision)
        return await self.read(reference)

    async def revision(self, reference: ResourceRef) -> ResourceRevision | None:
        if isinstance(reference, FileResourceRef):
            try:
                return await self._worker.run_sync(_file_revision, reference.path)
            except FileNotFoundError as error:
                raise ResourceNotFound(
                    "Resource was not found.", source=error
                ) from error
            except PermissionError as error:
                raise ResourceAccessDenied(
                    "Resource access was denied.", source=error
                ) from error
            except OSError as error:
                raise ResourceResolutionError(
                    "Resource revision inspection failed.", source=error
                ) from error
            except Exception as error:
                raise ResourceResolutionError(
                    f"Could not inspect resource {reference!r}.",
                    source=error,
                ) from error
        if isinstance(reference, PackageResourceRef):
            return ResourceRevision(f"package:{reference.package}:{reference.name}")
        if isinstance(reference, InlineResourceRef):
            return ResourceRevision(reference.digest)
        return None

    async def invalidate(self, reference: ResourceRef) -> None:
        del reference

    async def clear(self) -> None:
        return None


@dataclass(slots=True)
class _Inflight:
    event: anyio.Event
    refresh: bool
    content: ResourceContent | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class _CacheEntry:
    content: ResourceContent
    checked_at: float


@dataclass(frozen=True, slots=True)
class _LoadSlot:
    inflight: _Inflight
    stale: _CacheEntry | None
    owner: bool


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
        self._inflight: dict[object, _Inflight] = {}
        self._resident_bytes = 0
        self._lock = anyio.Lock()
        self._reset_lock = anyio.Lock()
        self._reset_all: anyio.Event | None = None
        self._reset_keys: dict[object, anyio.Event] = {}

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

    async def _acquire(
        self,
        key: object,
        *,
        refresh: bool,
    ) -> ResourceContent | _LoadSlot:
        while True:
            async with self._lock:
                reset = self._reset_all or self._reset_keys.get(key)
                if reset is None:
                    inflight = self._inflight.get(key)
                    if refresh and (inflight is None or not inflight.refresh):
                        entry = self._entries.pop(key, None)
                        if entry is not None:
                            self._resident_bytes -= len(entry.content.data)
                        inflight = _Inflight(anyio.Event(), refresh=True)
                        self._inflight[key] = inflight
                        return _LoadSlot(inflight, None, owner=True)

                    if inflight is not None:
                        self._record({"wait": 1})
                        return _LoadSlot(inflight, None, owner=False)

                    entry = self._entries.get(key)
                    if (
                        entry is not None
                        and time.monotonic() - entry.checked_at
                        < self._settings.revalidate_seconds
                    ):
                        self._entries.move_to_end(key)
                        self._record({"hit": 1})
                        return entry.content

                    inflight = _Inflight(anyio.Event(), refresh=False)
                    self._inflight[key] = inflight
                    return _LoadSlot(inflight, entry, owner=True)
            await reset.wait()

    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent:
        key = reference.cache_key
        while True:
            acquired = await self._acquire(key, refresh=refresh)
            if isinstance(acquired, ResourceContent):
                return acquired
            inflight = acquired.inflight
            if acquired.owner:
                stale = acquired.stale
                break
            await inflight.event.wait()
            if inflight.error is not None:
                raise inflight.error
            if inflight.content is None:
                refresh = refresh or inflight.refresh
                continue
            return inflight.content

        try:
            cache_hit = False
            if stale is not None:
                known = stale.content.revision
                if known is not None:
                    # The reader maps the held revision to a source-native
                    # conditional read (HTTP validators, stat compare); a
                    # NotModified outcome reuses the cached bytes.
                    outcome = await self._inner.read_conditional(reference, known)
                    if isinstance(outcome, NotModified):
                        content = stale.content
                        cache_hit = True
                    else:
                        content = outcome
                else:
                    content = await self._inner.read(reference)
            else:
                content = await self._inner.read(reference, refresh=refresh)

            with anyio.CancelScope(shield=True):
                async with self._lock:
                    events = {"hit": 1} if cache_hit else {"miss": 1, "load": 1}
                    if self._inflight.get(key) is inflight:
                        evictions = 0
                        if (
                            cache_hit
                            and stale is not None
                            and self._entries.get(key) is stale
                        ):
                            stale.checked_at = time.monotonic()
                            self._entries.move_to_end(key)
                        else:
                            evictions = self._store(key, content)
                        self._inflight.pop(key, None)
                        if evictions:
                            events["eviction"] = evictions
                    inflight.content = content
                    inflight.event.set()
                    self._record(events)
            return content
        except BaseException as error:
            cancelled = isinstance(error, anyio.get_cancelled_exc_class())
            with anyio.CancelScope(shield=True):
                async with self._lock:
                    if self._inflight.get(key) is inflight:
                        self._inflight.pop(key, None)
                    if not cancelled:
                        inflight.error = error
                    inflight.event.set()
                    self._record({"miss": 1})
            raise

    def _store(
        self,
        key: object,
        content: ResourceContent,
    ) -> int:
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._resident_bytes -= len(previous.content.data)
        size = len(content.data)
        if (
            self._settings.max_entries == 0
            or self._settings.max_bytes == 0
            or size > self._settings.max_bytes
        ):
            return 0
        self._entries[key] = _CacheEntry(content, time.monotonic())
        self._resident_bytes += size
        evictions = 0
        while (
            len(self._entries) > self._settings.max_entries
            or self._resident_bytes > self._settings.max_bytes
        ):
            _, evicted = self._entries.popitem(last=False)
            self._resident_bytes -= len(evicted.content.data)
            evictions += 1
        return evictions

    async def read_conditional(
        self,
        reference: ResourceRef,
        revision: ResourceRevision,
    ) -> ResourceContent | NotModified:
        return await self._inner.read_conditional(reference, revision)

    async def revision(self, reference: ResourceRef) -> ResourceRevision | None:
        return await self._inner.revision(reference)

    async def invalidate(self, reference: ResourceRef) -> None:
        key = reference.cache_key
        async with self._reset_lock:
            reset = anyio.Event()
            async with self._lock:
                self._reset_keys[key] = reset
                entry = self._entries.pop(key, None)
                if entry is not None:
                    self._resident_bytes -= len(entry.content.data)
                self._inflight.pop(key, None)
                self._record({})
            try:
                await self._inner.invalidate(reference)
            finally:
                with anyio.CancelScope(shield=True):
                    async with self._lock:
                        if self._reset_keys.get(key) is reset:
                            self._reset_keys.pop(key, None)
                        reset.set()

    async def clear(self) -> None:
        async with self._reset_lock:
            reset = anyio.Event()
            async with self._lock:
                self._reset_all = reset
                self._entries.clear()
                self._inflight.clear()
                self._resident_bytes = 0
                self._record({})
            try:
                await self._inner.clear()
            finally:
                with anyio.CancelScope(shield=True):
                    async with self._lock:
                        if self._reset_all is reset:
                            self._reset_all = None
                        reset.set()


def build_resource_reader(
    settings: ResourceCacheSettings,
    observer: CacheObserver,
    worker: WorkerExecutor,
    *,
    remote_transport: RemoteTransportExecutor,
    remote_access: RemoteAccessPolicy | None = None,
    remote_timeout_seconds: float = 30.0,
) -> CachingResourceReader:
    direct = CompositeResourceReader(
        worker,
        max_resource_bytes=settings.max_resource_bytes,
        remote_access=remote_access,
        remote_transport=remote_transport,
        remote_timeout_seconds=remote_timeout_seconds,
    )
    return CachingResourceReader(direct, settings=settings, observer=observer)


@asynccontextmanager
async def open_resource_reader(
    settings: ResourceCacheSettings,
    observer: CacheObserver,
    worker: WorkerExecutor,
    *,
    remote_access: RemoteAccessSettings | None = None,
) -> AsyncIterator[CachingResourceReader]:
    """Build a reader that owns its remote transport for standalone use.

    The composition root creates and closes the transport through the
    application lifecycle; callers outside that lifecycle use this context
    manager so the transport is always drained and closed on exit.
    """
    remote_settings = remote_access or RemoteAccessSettings()
    transport = RemoteTransportExecutor(
        max_concurrent_fetches=remote_settings.max_concurrent_fetches
    )
    try:
        yield build_resource_reader(
            settings,
            observer,
            worker,
            remote_transport=transport,
            remote_access=ConfiguredRemoteAccessPolicy(remote_settings),
            remote_timeout_seconds=remote_settings.request_timeout_seconds,
        )
    finally:
        with anyio.CancelScope(shield=True):
            await transport.aclose()


__all__ = [
    "AnyioWorkerExecutor",
    "CachingResourceReader",
    "CompositeResourceReader",
    "ConfiguredLocalAccessPolicy",
    "RemoteTransportExecutor",
    "build_resource_reader",
    "open_resource_reader",
]
