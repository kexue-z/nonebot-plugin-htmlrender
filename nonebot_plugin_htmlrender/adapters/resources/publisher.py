from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from importlib import import_module
from pathlib import Path
import time
from typing import TYPE_CHECKING
import uuid

import anyio
from nonebot.log import logger

if TYPE_CHECKING:
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.responses import Response

    from nonebot_plugin_htmlrender.resources.config import AssetPublisherSettings
    from nonebot_plugin_htmlrender.resources.observation import CacheObserver
    from nonebot_plugin_htmlrender.resources.ports import (
        LocalAccessPolicy,
        WorkerExecutor,
    )

from nonebot_plugin_htmlrender.rendering.errors import ProviderLifecycleError
from nonebot_plugin_htmlrender.resources.errors import (
    ResourceAccessDenied,
    ResourceNotFound,
    ResourceResolutionError,
    ResourceSizeExceeded,
)


@dataclass(slots=True)
class _Entry:
    url: str
    expires_at: float
    leases: set[str]


@dataclass(slots=True)
class _Inflight:
    event: anyio.Event
    epoch: int
    url: str | None = None
    error: BaseException | None = None
    leases: set[str] = field(default_factory=set)


def _read_consistent(path: Path, max_resource_bytes: int) -> tuple[bytes, str]:
    resolved = path.expanduser().resolve()
    for _ in range(3):
        before = resolved.stat()
        if max_resource_bytes > 0 and before.st_size > max_resource_bytes:
            raise ResourceSizeExceeded(
                f"Resource {resolved} exceeds the configured "
                f"{max_resource_bytes}-byte publish limit."
            )
        with resolved.open("rb") as stream:
            data = (
                stream.read()
                if max_resource_bytes == 0
                else stream.read(max_resource_bytes + 1)
            )
        if max_resource_bytes > 0 and len(data) > max_resource_bytes:
            raise ResourceSizeExceeded(
                f"Resource {resolved} exceeds the configured "
                f"{max_resource_bytes}-byte publish limit."
            )
        after = resolved.stat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) and len(data) == after.st_size:
            return data, resolved.suffix
    raise RuntimeError(f"File changed repeatedly while publishing: {resolved}")


def _prewarm_candidates(
    roots: tuple[Path, ...],
    extensions: frozenset[str],
    limit: int,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for configured in roots:
        root = configured.expanduser().resolve()
        paths = (root,) if root.is_file() else root.rglob("*") if root.is_dir() else ()
        for path in paths:
            if not path.is_file() or (
                extensions and path.suffix.lower() not in extensions
            ):
                continue
            candidates.append(path)
            if len(candidates) >= limit:
                return tuple(candidates)
    return tuple(candidates)


def _request_guard_values(settings: AssetPublisherSettings) -> tuple[str, str]:
    header_name = settings.request_header_name.strip()
    if settings.request_header_value:
        return header_name, settings.request_header_value
    try:
        machineid = import_module("machineid")
        identity = str(machineid.id()).strip()
    except Exception:
        identity = f"mac:{uuid.getnode():012x}"
    value = sha256(f"{settings.request_header_salt}:{identity}".encode()).hexdigest()
    return header_name, value


def install_filehost_request_guard(settings: AssetPublisherSettings) -> bool:
    """Install the host middleware before the ASGI application starts.

    ``Application.startup()`` can run from inside ASGI lifespan, which is too
    late for FastAPI middleware mutation. The NoneBot bootstrap calls this
    adapter while importing the plugin instead.
    """
    try:
        from fastapi import FastAPI, Request  # noqa: PLC0415
        from fastapi.responses import PlainTextResponse  # noqa: PLC0415
        from nonebot import get_driver  # noqa: PLC0415
        from nonebot.drivers import ASGIMixin  # noqa: PLC0415
    except Exception as error:
        logger.debug("Filehost request guard is unavailable: {}", error)
        return False

    try:
        driver = get_driver()
    except Exception as error:
        logger.debug("Filehost request guard has no active NoneBot driver: {}", error)
        return False
    if not isinstance(driver, ASGIMixin) or not isinstance(driver.server_app, FastAPI):
        return False

    app = driver.server_app
    guard = _request_guard_values(settings)
    state_key = "_htmlrender_filehost_guard"
    installed = getattr(app.state, state_key, None)
    if installed is not None:
        if installed != guard:
            raise ProviderLifecycleError(
                "The ASGI application already has a filehost request guard "
                "with different settings."
            )
        return True
    if app.middleware_stack is not None:
        raise ProviderLifecycleError(
            "The filehost request guard must be installed before the ASGI "
            "application starts. Load nonebot-plugin-htmlrender during plugin "
            "initialization."
        )

    header_name, header_value = guard

    @app.middleware("http")
    async def _guard(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        is_filehost = request.url.path.startswith("/filehost/")
        if is_filehost and request.headers.get(header_name) != header_value:
            return PlainTextResponse("Forbidden", status_code=403)
        response = await call_next(request)
        if is_filehost:
            response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    setattr(app.state, state_key, guard)
    logger.info(
        "Filehost request guard enabled with header {!r}",
        header_name,
    )
    return True


class FilehostAssetPublisher:
    """Instance-owned, content-addressed publisher for nonebot-plugin-filehost."""

    def __init__(
        self,
        *,
        settings: AssetPublisherSettings,
        observer: CacheObserver,
        worker: WorkerExecutor,
        local_access: LocalAccessPolicy,
    ) -> None:
        self._settings = settings
        self._observer = observer
        self._worker = worker
        self._local_access = local_access
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._inflight: dict[tuple[str, str], _Inflight] = {}
        self._epoch = 0
        self._lock = anyio.Lock()
        self._closed = False
        self._drained = anyio.Event()
        self._drained.set()
        self._header_name, self._header_value = _request_guard_values(settings)

    def create_lease(self) -> str:
        return f"lease:{uuid.uuid4().hex}"

    def request_headers(self) -> dict[str, str]:
        return {self._header_name: self._header_value}

    async def startup(self) -> None:
        async with self._lock:
            if self._closed:
                raise ProviderLifecycleError(
                    "The filehost publisher is already closed."
                )
        await self._prewarm()

    async def _prewarm(self) -> None:
        if not self._settings.prewarm_enabled or self._settings.prewarm_max_files == 0:
            return
        extensions = frozenset(
            value.lower() if value.startswith(".") else f".{value.lower()}"
            for value in self._settings.prewarm_extensions
            if value
        )
        candidates = await self._worker.run_sync(
            _prewarm_candidates,
            self._settings.prewarm_paths,
            extensions,
            self._settings.prewarm_max_files,
        )
        for path in candidates:
            try:
                authorized = self._local_access.authorize(
                    path,
                )
                data, suffix = await self._worker.run_sync(
                    _read_consistent,
                    authorized,
                    self._settings.max_resource_bytes,
                )
                await self.publish(data, suffix=suffix)
            except Exception as error:  # noqa: PERF203 -- optional files are isolated
                logger.warning(
                    "Could not prewarm filehost resource {}: {}", path, error
                )

    async def aclose(self) -> None:
        async with self._lock:
            self._closed = True
            drained = self._drained
        with anyio.move_on_after(30, shield=True) as scope:
            await drained.wait()
        if scope.cancel_called:
            raise ProviderLifecycleError(
                "Timed out waiting for in-flight filehost publishes to finish."
            )
        async with self._lock:
            self._entries.clear()

    async def clear(self) -> None:
        """Clear published URL mappings without terminating the instance."""
        async with self._lock:
            self._epoch += 1
            self._entries.clear()

    async def _upload(self, data: bytes, suffix: str) -> str:
        module = import_module("nonebot_plugin_filehost")
        file_host = (
            module.FileHost(data, suffix=suffix) if suffix else module.FileHost(data)
        )
        return str(await file_host.to_url())

    def _record(self, events: dict[str, int]) -> None:
        try:
            self._observer.record("filehost", events, len(self._entries))
        except Exception:
            return

    async def publish(
        self,
        value: str | Path | bytes,
        *,
        lease_id: str | None = None,
        suffix: str | None = None,
    ) -> str:
        if isinstance(value, (str, Path)):
            if suffix is not None:
                raise ValueError("suffix cannot override a filesystem resource suffix")
            try:
                path = self._local_access.authorize(Path(value))
                data, resolved_suffix = await self._worker.run_sync(
                    _read_consistent,
                    path,
                    self._settings.max_resource_bytes,
                )
            except ResourceResolutionError:
                raise
            except FileNotFoundError as error:
                raise ResourceNotFound(str(error)) from error
            except PermissionError as error:
                raise ResourceAccessDenied(str(error)) from error
            except Exception as error:
                raise ResourceResolutionError(
                    f"Could not read resource for publishing: {error}"
                ) from error
            suffix = resolved_suffix
        else:
            data = value
            if (
                self._settings.max_resource_bytes > 0
                and len(data) > self._settings.max_resource_bytes
            ):
                raise ResourceSizeExceeded(
                    "Resource exceeds the configured "
                    f"{self._settings.max_resource_bytes}-byte publish limit."
                )
        normalized_suffix = (
            "" if not suffix else suffix if suffix.startswith(".") else f".{suffix}"
        )
        key = (sha256(data).hexdigest(), normalized_suffix.lower())
        now = time.monotonic()
        async with self._lock:
            if self._closed:
                raise ProviderLifecycleError("The filehost publisher is closed.")
            expired = [
                cache_key
                for cache_key, entry in self._entries.items()
                if not entry.leases and entry.expires_at <= now
            ]
            for cache_key in expired:
                self._entries.pop(cache_key, None)
            entry = self._entries.get(key)
            if entry is not None:
                if lease_id is not None:
                    entry.leases.add(lease_id)
                self._record({"hit": 1})
                return entry.url
            inflight = self._inflight.get(key)
            owner = inflight is None
            if inflight is None:
                inflight = _Inflight(anyio.Event(), self._epoch)
                self._inflight[key] = inflight
                if len(self._inflight) == 1:
                    self._drained = anyio.Event()
            if lease_id is not None:
                inflight.leases.add(lease_id)
        if not owner:
            await inflight.event.wait()
            if inflight.error is not None:
                raise inflight.error
            if inflight.url is None:
                return await self.publish(
                    data, lease_id=lease_id, suffix=normalized_suffix
                )
            return inflight.url
        try:
            url = await self._upload(data, normalized_suffix)
            with anyio.CancelScope(shield=True):
                async with self._lock:
                    if inflight.epoch == self._epoch:
                        self._entries[key] = _Entry(
                            url,
                            time.monotonic() + self._settings.cache_ttl_seconds,
                            set(inflight.leases),
                        )
                    self._inflight.pop(key, None)
                    if not self._inflight:
                        self._drained.set()
                    inflight.url = url
                    inflight.event.set()
                    self._record({"miss": 1, "load": 1})
            return url
        except BaseException as error:
            published_error: BaseException = error
            if isinstance(error, Exception) and not isinstance(
                error, ResourceResolutionError
            ):
                if isinstance(error, ModuleNotFoundError):
                    published_error = ResourceResolutionError(
                        "The filehost resource policy requires the "
                        "nonebot-plugin-filehost extra."
                    )
                else:
                    published_error = ResourceResolutionError(
                        f"Could not publish resource: {error}"
                    )
            with anyio.CancelScope(shield=True):
                async with self._lock:
                    self._inflight.pop(key, None)
                    if not self._inflight:
                        self._drained.set()
                    inflight.error = published_error
                    inflight.event.set()
            if published_error is error:
                raise
            raise published_error from error

    async def release(self, lease_id: str) -> None:
        async with self._lock:
            now = time.monotonic()
            for inflight in self._inflight.values():
                inflight.leases.discard(lease_id)
            for entry in self._entries.values():
                if lease_id in entry.leases:
                    entry.leases.remove(lease_id)
                    entry.expires_at = now + self._settings.cache_ttl_seconds


__all__ = ["FilehostAssetPublisher", "install_filehost_request_guard"]
