"""Host-owned storage and route for htmlrender-published assets.

``HostedAssetStore`` is the process-level owner of every asset htmlrender
publishes to the executing browser: it holds the temporary directory, the
per-asset guard registry, the capacity ledger, and the shutdown hook. The
bootstrap installs the fixed internal mount ``/_htmlrender/assets/`` on the
ASGI application before it starts; publishers only interact through their
own :class:`HostedAssetNamespace` handle and can never touch another
application's assets or another plugin's routes.

Capacity is a hard budget: entries and bytes are reserved before a file is
written, only lease-free assets are evictable (their files are deleted), and
a store whose remaining assets are all leased raises a stable capacity
error. TTLs govern reuse freshness in the publisher, never capacity.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import mimetypes
from pathlib import Path
import shutil
import tempfile
from typing import TYPE_CHECKING, final
from urllib.parse import quote
import uuid

import anyio
from anyio.to_thread import run_sync
from nonebot.log import logger

from nonebot_plugin_htmlrender.rendering.errors import ProviderLifecycleError
from nonebot_plugin_htmlrender.resources.errors import ResourceResolutionError
from nonebot_plugin_htmlrender.resources.headers import (
    RequestHeaderConflict,
    combine_request_capabilities,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from nonebot_plugin_htmlrender.resources.config import AssetPublisherSettings

HOSTED_ASSET_MOUNT = "/_htmlrender/assets"
_STORE_STATE_KEY = "_htmlrender_hosted_asset_store"


class HostedAssetCapacityError(ResourceResolutionError):
    """The hosted asset budget is exhausted by lease-pinned assets."""


@dataclass(slots=True)
class _HostedAsset:
    namespace: str
    name: str
    path: Path
    size: int
    media_type: str | None
    headers: Mapping[str, str]
    leases: set[str] = field(default_factory=set)


@final
class HostedAssetStore:
    """Content-addressed, capacity-bounded storage behind the fixed mount."""

    def __init__(self, *, max_entries: int, max_bytes: int) -> None:
        if max_entries <= 0 or max_bytes <= 0:
            raise ValueError("Hosted asset capacity limits must be positive.")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._directory = Path(tempfile.mkdtemp(prefix="htmlrender-assets-"))
        self._entries: OrderedDict[tuple[str, str], _HostedAsset] = OrderedDict()
        self._resident_bytes = 0
        self._reserved_entries = 0
        self._reserved_bytes = 0
        self._lock = anyio.Lock()
        self._closed = False

    @property
    def limits(self) -> tuple[int, int]:
        return self._max_entries, self._max_bytes

    def open_namespace(
        self,
        *,
        headers: Mapping[str, str],
        public_base_url: str,
    ) -> HostedAssetNamespace:
        """Hand one application publisher its private namespace handle."""
        return HostedAssetNamespace(
            store=self,
            namespace=uuid.uuid4().hex,
            headers=dict(headers),
            public_base_url=public_base_url,
        )

    def lookup(self, namespace: str, name: str) -> _HostedAsset | None:
        """Resolve one asset for the route handler; ``None`` means 404."""
        return self._entries.get((namespace, name))

    def _evict_locked(self, incoming_bytes: int) -> list[Path]:
        """Reserve room for one incoming asset, returning files to delete."""
        if incoming_bytes > self._max_bytes:
            raise HostedAssetCapacityError(
                "Hosted asset exceeds the configured "
                f"{self._max_bytes}-byte publish budget."
            )
        removed: list[Path] = []

        def over_budget() -> bool:
            entries = (
                len(self._entries) + self._reserved_entries + 1 - self._max_entries
            )
            resident = (
                self._resident_bytes
                + self._reserved_bytes
                + incoming_bytes
                - self._max_bytes
            )
            return entries > 0 or resident > 0

        while over_budget():
            victim_key = next(
                (key for key, asset in self._entries.items() if not asset.leases),
                None,
            )
            if victim_key is None:
                raise HostedAssetCapacityError(
                    "Hosted asset capacity is exhausted and every resident "
                    "asset is pinned by an active render lease."
                )
            victim = self._entries.pop(victim_key)
            self._resident_bytes -= victim.size
            removed.append(victim.path)
        return removed

    async def put(
        self,
        namespace: str,
        name: str,
        data: bytes,
        *,
        headers: Mapping[str, str],
        lease_ids: Iterable[str] = (),
    ) -> None:
        """Admit one content-addressed asset under the capacity budget.

        Callers singleflight per ``(namespace, name)``; a repeated put for a
        resident asset only attaches leases and refreshes recency.
        """
        key = (namespace, name)
        size = len(data)
        async with self._lock:
            if self._closed:
                raise ProviderLifecycleError("The hosted asset store is closed.")
            existing = self._entries.get(key)
            if existing is not None:
                try:
                    combine_request_capabilities(existing.headers, headers)
                except RequestHeaderConflict as error:
                    raise ResourceResolutionError(
                        "Conflicting request capabilities for one hosted "
                        "asset identity.",
                        source=error,
                    ) from error
                existing.leases.update(lease_ids)
                self._entries.move_to_end(key)
                return
            removed = self._evict_locked(size)
            self._reserved_entries += 1
            self._reserved_bytes += size
        try:
            for stale in removed:
                await run_sync(_unlink_quietly, stale)
            path = self._directory / namespace / name
            await run_sync(_write_asset_file, path, data)
        except BaseException:
            async with self._lock:
                self._reserved_entries -= 1
                self._reserved_bytes -= size
            raise
        async with self._lock:
            self._reserved_entries -= 1
            self._reserved_bytes -= size
            if self._closed:
                await run_sync(_unlink_quietly, path)
                raise ProviderLifecycleError("The hosted asset store is closed.")
            self._entries[key] = _HostedAsset(
                namespace=namespace,
                name=name,
                path=path,
                size=size,
                media_type=mimetypes.guess_type(name)[0],
                headers=dict(headers),
                leases=set(lease_ids),
            )
            self._resident_bytes += size
            self._entries.move_to_end(key)

    async def attach(self, namespace: str, name: str, lease_id: str) -> bool:
        """Pin a resident asset to a lease; ``False`` when it was evicted."""
        async with self._lock:
            asset = self._entries.get((namespace, name))
            if asset is None:
                return False
            asset.leases.add(lease_id)
            self._entries.move_to_end((namespace, name))
            return True

    async def touch(self, namespace: str, name: str) -> bool:
        """Refresh recency of a resident asset; ``False`` when evicted."""
        async with self._lock:
            if (namespace, name) not in self._entries:
                return False
            self._entries.move_to_end((namespace, name))
            return True

    async def release(self, namespace: str, lease_id: str) -> None:
        async with self._lock:
            for asset in self._entries.values():
                if asset.namespace == namespace:
                    asset.leases.discard(lease_id)

    async def _drop_namespace(self, namespace: str, *, keep_leased: bool) -> None:
        async with self._lock:
            victims = [
                key
                for key, asset in self._entries.items()
                if asset.namespace == namespace and not (keep_leased and asset.leases)
            ]
            removed: list[Path] = []
            for key in victims:
                asset = self._entries.pop(key)
                self._resident_bytes -= asset.size
                removed.append(asset.path)
        for stale in removed:
            await run_sync(_unlink_quietly, stale)

    async def clear_namespace(self, namespace: str) -> None:
        """Drop the namespace's lease-free assets and delete their files."""
        await self._drop_namespace(namespace, keep_leased=True)

    async def close_namespace(self, namespace: str) -> None:
        """Release everything one application publisher ever published."""
        await self._drop_namespace(namespace, keep_leased=False)

    async def aclose(self) -> None:
        """Driver-shutdown hook: drop every asset and the temp directory."""
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            self._entries.clear()
            self._resident_bytes = 0
        await run_sync(_remove_tree_quietly, self._directory)


@final
class HostedAssetNamespace:
    """One application publisher's private window into the host store."""

    def __init__(
        self,
        *,
        store: HostedAssetStore,
        namespace: str,
        headers: Mapping[str, str],
        public_base_url: str,
    ) -> None:
        self._store = store
        self._namespace = namespace
        self._headers = dict(headers)
        self._base_url = public_base_url

    def url_for(self, name: str) -> str:
        return (
            f"{self._base_url}{quote(self._namespace, safe='')}/{quote(name, safe='')}"
        )

    async def put(
        self,
        name: str,
        data: bytes,
        *,
        lease_ids: Iterable[str] = (),
    ) -> str:
        await self._store.put(
            self._namespace,
            name,
            data,
            headers=self._headers,
            lease_ids=lease_ids,
        )
        return self.url_for(name)

    async def attach(self, name: str, lease_id: str) -> bool:
        return await self._store.attach(self._namespace, name, lease_id)

    async def touch(self, name: str) -> bool:
        return await self._store.touch(self._namespace, name)

    async def release(self, lease_id: str) -> None:
        await self._store.release(self._namespace, lease_id)

    async def clear(self) -> None:
        await self._store.clear_namespace(self._namespace)

    async def aclose(self) -> None:
        await self._store.close_namespace(self._namespace)


def _write_asset_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete a hosted asset file.")


def _remove_tree_quietly(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def install_hosted_asset_store(
    settings: AssetPublisherSettings,
) -> HostedAssetStore | None:
    """Install the fixed internal mount before the ASGI application starts.

    Idempotent per application; a second installation with different
    capacity limits fails instead of silently re-sizing the shared store.
    Returns ``None`` on non-ASGI/non-FastAPI hosts.
    """
    try:
        from fastapi import FastAPI, Request, Response  # noqa: PLC0415
        from fastapi.responses import (  # noqa: PLC0415
            FileResponse,
            PlainTextResponse,
        )
        from nonebot import get_driver  # noqa: PLC0415
        from nonebot.drivers import ASGIMixin  # noqa: PLC0415
    except Exception as error:
        logger.debug("Hosted asset store is unavailable: {}", error)
        return None

    try:
        driver = get_driver()
    except Exception as error:
        logger.debug("Hosted asset store has no active NoneBot driver: {}", error)
        return None
    if not isinstance(driver, ASGIMixin) or not isinstance(driver.server_app, FastAPI):
        return None

    app = driver.server_app
    installed = getattr(app.state, _STORE_STATE_KEY, None)
    if isinstance(installed, HostedAssetStore):
        if installed.limits != (settings.max_entries, settings.max_bytes):
            raise ProviderLifecycleError(
                "The ASGI application already hosts an htmlrender asset "
                "store with different capacity limits."
            )
        return installed

    store = HostedAssetStore(
        max_entries=settings.max_entries,
        max_bytes=settings.max_bytes,
    )

    async def _serve_hosted_asset(namespace, name, request):
        asset = store.lookup(namespace, name)
        if asset is None:
            return PlainTextResponse("Not Found", status_code=404)
        for header, expected in asset.headers.items():
            if request.headers.get(header) != expected:
                return PlainTextResponse("Forbidden", status_code=403)
        return FileResponse(
            asset.path,
            media_type=asset.media_type or "application/octet-stream",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    # This module uses ``from __future__ import annotations`` while FastAPI
    # names are imported locally, so inline annotations would be unresolvable
    # strings at route registration; assign real objects instead.
    _serve_hosted_asset.__annotations__ = {
        "namespace": str,
        "name": str,
        "request": Request,
        "return": Response,
    }
    app.get(HOSTED_ASSET_MOUNT + "/{namespace}/{name}")(_serve_hosted_asset)

    on_shutdown = getattr(driver, "on_shutdown", None)
    if callable(on_shutdown):
        on_shutdown(store.aclose)
    setattr(app.state, _STORE_STATE_KEY, store)
    logger.info("Hosted asset store mounted at {}/.", HOSTED_ASSET_MOUNT)
    return store


def acquire_hosted_asset_store() -> HostedAssetStore | None:
    """Fetch the installed store from the active driver, if any."""
    try:
        from fastapi import FastAPI  # noqa: PLC0415
        from nonebot import get_driver  # noqa: PLC0415
        from nonebot.drivers import ASGIMixin  # noqa: PLC0415
    except Exception:
        return None
    try:
        driver = get_driver()
    except Exception:
        return None
    if not isinstance(driver, ASGIMixin) or not isinstance(driver.server_app, FastAPI):
        return None
    installed = getattr(driver.server_app.state, _STORE_STATE_KEY, None)
    return installed if isinstance(installed, HostedAssetStore) else None


__all__ = [
    "HOSTED_ASSET_MOUNT",
    "HostedAssetCapacityError",
    "HostedAssetNamespace",
    "HostedAssetStore",
    "acquire_hosted_asset_store",
    "install_hosted_asset_store",
]
