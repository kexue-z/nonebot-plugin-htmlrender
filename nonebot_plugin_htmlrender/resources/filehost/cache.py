"""Content-addressed filehost URL mappings and lease management.

The cache in this module owns URL mappings only. The optional
``nonebot-plugin-filehost`` dependency owns the physical files behind those URLs
and currently releases them at process shutdown rather than per mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import import_module
from io import BytesIO
import os
from pathlib import Path
import re
import time
from typing import TypedDict
import uuid

import anyio
from anyio.lowlevel import checkpoint_if_cancelled
from anyio.to_thread import run_sync

from nonebot_plugin_htmlrender.resources.config import get_resource_config
from nonebot_plugin_htmlrender.utils.telemetry import record_filehost_cache_metrics

FilehostInput = Path | bytes | bytearray | BytesIO | str
_SAFE_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


@dataclass(frozen=True, slots=True)
class _PathRevision:
    """Filesystem identity for one path snapshot."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, stat: os.stat_result) -> _PathRevision:
        return cls(
            device=stat.st_dev,
            inode=stat.st_ino,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            ctime_ns=stat.st_ctime_ns,
        )


@dataclass(frozen=True, slots=True)
class _ResourceSnapshot:
    """Immutable bytes and content identity uploaded as one filehost blob."""

    key: str
    digest: str
    data: bytes
    suffix: str = ""
    source_path: Path | None = None
    revision: _PathRevision | None = None

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class _PathIndexEntry:
    revision: _PathRevision
    blob_key: str


class _CacheEntry(TypedDict):
    """One cached URL mapping for an immutable content digest."""

    url: str
    digest: str
    size: int
    hits: int
    last_access_ns: int
    lease_ref_count: int
    mapping_expires_at_ns: int | None
    path_aliases: set[Path]
    suffix: str


@dataclass(frozen=True, slots=True)
class FilehostCacheMetrics:
    """Low-cardinality process-local filehost cache metrics."""

    uploaded_bytes: int
    dedup_hits: int
    active_mappings: int
    active_leases: int
    physical_cleanup_capable: int = 0


@dataclass(slots=True)
class _FilehostCounters:
    uploaded_bytes: int = 0
    dedup_hits: int = 0


_FILEHOST_RESOURCE_LOCK = anyio.Lock()
_FILEHOST_RESOURCE_CACHE: dict[str, _CacheEntry] = {}
_FILEHOST_PATH_INDEX: dict[Path, _PathIndexEntry] = {}
_FILEHOST_LEASES: dict[str, set[str]] = {}
_FILEHOST_COUNTERS = _FilehostCounters()


@dataclass
class _InflightResourceUpload:
    """Shared outcome for one content-addressed upload."""

    event: anyio.Event
    suffix: str
    url: str | None = None
    error: Exception | None = None


_FILEHOST_RESOURCE_INFLIGHT: dict[str, _InflightResourceUpload] = {}


def _metrics_snapshot_locked() -> FilehostCacheMetrics:
    return FilehostCacheMetrics(
        uploaded_bytes=_FILEHOST_COUNTERS.uploaded_bytes,
        dedup_hits=_FILEHOST_COUNTERS.dedup_hits,
        active_mappings=len(_FILEHOST_RESOURCE_CACHE),
        active_leases=len(_FILEHOST_LEASES),
    )


def _emit_metrics(event: str, value: int, metrics: FilehostCacheMetrics) -> None:
    record_filehost_cache_metrics(
        event,
        value,
        metrics.active_mappings,
        metrics.active_leases,
        metrics.physical_cleanup_capable,
    )


def _normalize_filehost_input(value: FilehostInput) -> Path | bytes:
    """Normalize supported inputs without performing blocking path resolution."""
    if isinstance(value, Path):
        return value.expanduser()
    if isinstance(value, str):
        return Path(value).expanduser()
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, BytesIO):
        return value.getvalue()
    return value


def _normalize_suffix(suffix: str | None) -> str:
    if suffix is None:
        return ""
    normalized = suffix.strip().lower()
    if not normalized:
        return ""
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    if _SAFE_SUFFIX_RE.fullmatch(normalized) is None:
        raise ValueError(f"Unsafe filehost resource suffix: {suffix!r}")
    return normalized


def _stat_signature(path: Path) -> tuple[int, int]:
    """Return the legacy mtime/size signature used by compatibility tests."""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _cache_key(path: Path) -> str:
    """Return the legacy canonical path key.

    URL mappings themselves are keyed by SHA-256 digest; this helper remains for
    compatibility with the private facade exported by ``resources.filehost``.
    """
    return str(path.resolve())


def _normalize_and_snapshot_path(path: Path) -> tuple[Path, str, int, int]:
    """Return legacy path metadata without publishing a URL mapping."""
    resolved = path.expanduser().resolve()
    key = _cache_key(resolved)
    mtime_ns, size = _stat_signature(resolved)
    return resolved, key, mtime_ns, size


async def _normalize_and_snapshot_path_async(path: Path) -> tuple[Path, str, int, int]:
    return await run_sync(_normalize_and_snapshot_path, path)


def _blob_identity(data: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(data).hexdigest()
    return f"sha256:{digest}", digest


def _snapshot_bytes(data: bytes, suffix: str = "") -> _ResourceSnapshot:
    key, digest = _blob_identity(data)
    return _ResourceSnapshot(key=key, digest=digest, data=data, suffix=suffix)


def _normalize_and_stat_path(path: Path) -> tuple[Path, _PathRevision]:
    resolved = path.expanduser().resolve()
    return resolved, _PathRevision.from_stat(resolved.stat())


def _read_consistent_path_snapshot(path: Path) -> _ResourceSnapshot:
    resolved = path.expanduser().resolve()
    for _ in range(3):
        with resolved.open("rb") as file:
            before = _PathRevision.from_stat(os.fstat(file.fileno()))
            data = file.read()
            after = _PathRevision.from_stat(os.fstat(file.fileno()))
        if before == after and len(data) == after.size:
            key, digest = _blob_identity(data)
            return _ResourceSnapshot(
                key=key,
                digest=digest,
                data=data,
                suffix=_normalize_suffix(resolved.suffix),
                source_path=resolved,
                revision=after,
            )
    raise RuntimeError(f"File changed repeatedly while reading: {resolved}")


def _url_mapping_ttl_ns() -> int:
    """Return the URL mapping TTL; it does not control physical hosted files."""
    cfg = get_resource_config()
    ttl = float(cfg.filehost_cache_ttl_seconds)
    return int(ttl * 1_000_000_000)


def _ttl_ns() -> int:
    """Compatibility alias for the URL mapping TTL."""
    return _url_mapping_ttl_ns()


def _compute_mapping_expire_at(now_ns: int) -> int:
    return now_ns + _url_mapping_ttl_ns()


def _compute_expire_at(now_ns: int) -> int:
    """Compatibility alias for URL mapping expiration."""
    return _compute_mapping_expire_at(now_ns)


def _remove_mapping_locked(key: str) -> None:
    entry = _FILEHOST_RESOURCE_CACHE.pop(key, None)
    if entry is None:
        return
    for path in entry["path_aliases"]:
        indexed = _FILEHOST_PATH_INDEX.get(path)
        if indexed is not None and indexed.blob_key == key:
            _FILEHOST_PATH_INDEX.pop(path, None)


def _evict_expired_resources_locked(now_ns: int) -> None:
    """Evict expired URL mappings without claiming physical-file cleanup."""
    expired_keys = [
        key
        for key, entry in _FILEHOST_RESOURCE_CACHE.items()
        if (expires_at_ns := entry["mapping_expires_at_ns"]) is not None
        if entry["lease_ref_count"] <= 0 and expires_at_ns <= now_ns
    ]
    for key in expired_keys:
        _remove_mapping_locked(key)


def _attach_key_to_lease_locked(lease_id: str, key: str) -> None:
    """Attach an exact content revision to a live lease."""
    lease_keys = _FILEHOST_LEASES.get(lease_id)
    if lease_keys is None or key in lease_keys:
        return
    entry = _FILEHOST_RESOURCE_CACHE.get(key)
    if entry is None:
        return
    lease_keys.add(key)
    entry["lease_ref_count"] += 1
    entry["mapping_expires_at_ns"] = None


def _set_path_alias_locked(snapshot: _ResourceSnapshot) -> None:
    path = snapshot.source_path
    revision = snapshot.revision
    if path is None or revision is None:
        return
    entry = _FILEHOST_RESOURCE_CACHE.get(snapshot.key)
    if entry is None:
        return

    previous = _FILEHOST_PATH_INDEX.get(path)
    if previous is not None and previous.blob_key != snapshot.key:
        previous_entry = _FILEHOST_RESOURCE_CACHE.get(previous.blob_key)
        if previous_entry is not None:
            previous_entry["path_aliases"].discard(path)

    _FILEHOST_PATH_INDEX[path] = _PathIndexEntry(
        revision=revision,
        blob_key=snapshot.key,
    )
    entry["path_aliases"].add(path)


def _touch_mapping_locked(
    key: str,
    *,
    suffix: str,
    lease_id: str | None,
    now_ns: int,
) -> str | None:
    entry = _FILEHOST_RESOURCE_CACHE.get(key)
    if entry is None:
        return None
    existing_suffix = entry.get("suffix", "")
    if suffix and existing_suffix != suffix:
        raise RuntimeError(
            "Identical filehost content was requested with incompatible suffixes: "
            f"{existing_suffix or '<none>'!r} and {suffix!r}."
        )
    entry["hits"] += 1
    entry["last_access_ns"] = now_ns
    if lease_id is not None:
        _attach_key_to_lease_locked(lease_id, key)
    elif entry["lease_ref_count"] <= 0:
        entry["mapping_expires_at_ns"] = _compute_mapping_expire_at(now_ns)
    return entry["url"]


def create_filehost_lease() -> str:
    """Create a lease that pins exact blob URL mappings until release."""
    lease_id = f"lease:{uuid.uuid4().hex}"
    _FILEHOST_LEASES.setdefault(lease_id, set())
    _emit_metrics("state", 0, _metrics_snapshot_locked())
    return lease_id


async def release_filehost_lease(lease_id: str) -> None:
    """Release URL mappings pinned by a lease.

    Physical files remain owned by ``nonebot-plugin-filehost`` and are not
    deleted by this operation.
    """
    now_ns = time.time_ns()
    async with _FILEHOST_RESOURCE_LOCK:
        lease_keys = _FILEHOST_LEASES.pop(lease_id, set())
        for key in lease_keys:
            entry = _FILEHOST_RESOURCE_CACHE.get(key)
            if entry is None:
                continue
            ref_count = max(0, entry["lease_ref_count"] - 1)
            entry["lease_ref_count"] = ref_count
            if ref_count == 0:
                entry["mapping_expires_at_ns"] = _compute_mapping_expire_at(now_ns)
        _evict_expired_resources_locked(now_ns)
        metrics = _metrics_snapshot_locked()
    _emit_metrics("state", 0, metrics)


async def prune_filehost_cache() -> None:
    """Prune expired URL mappings, not physical files owned by filehost."""
    now_ns = time.time_ns()
    async with _FILEHOST_RESOURCE_LOCK:
        _evict_expired_resources_locked(now_ns)
        metrics = _metrics_snapshot_locked()
    _emit_metrics("state", 0, metrics)


async def get_filehost_cache_metrics() -> FilehostCacheMetrics:
    """Return one consistent snapshot without paths, URLs, or resource names."""

    async with _FILEHOST_RESOURCE_LOCK:
        return _metrics_snapshot_locked()


async def filehost_url(
    value: FilehostInput,
    *,
    lease_id: str | None = None,
    suffix: str | None = None,
) -> str:
    """Return a content-addressed filehost URL for a path or byte snapshot."""
    normalized = _normalize_filehost_input(value)
    if isinstance(normalized, Path):
        if suffix is not None:
            raise ValueError("suffix cannot override a filesystem resource suffix")
        return await _filehost_url_from_path(normalized, lease_id=lease_id)
    normalized_suffix = _normalize_suffix(suffix)
    snapshot = await run_sync(_snapshot_bytes, normalized, normalized_suffix)
    return await _filehost_url_from_snapshot(snapshot, lease_id=lease_id)


async def _filehost_upload(value: FilehostInput, *, suffix: str = "") -> str:
    """Upload one immutable byte snapshot and return its external URL."""
    suffix = _normalize_suffix(suffix)
    try:
        module = import_module("nonebot_plugin_filehost")
        file_host_cls = module.FileHost
    except Exception as e:
        raise RuntimeError(
            "nonebot-plugin-filehost is required for filehost resource resolution."
        ) from e

    if isinstance(value, bytearray):
        value = bytes(value)
    host = file_host_cls(value, suffix=suffix) if suffix else file_host_cls(value)
    url = await host.to_url()
    return str(url)


async def _filehost_url_from_path(path: Path, *, lease_id: str | None = None) -> str:
    """Resolve a path through a consistent snapshot and digest-keyed mapping."""
    resolved, revision = await run_sync(_normalize_and_stat_path, path)
    now_ns = time.time_ns()
    cached_url: str | None = None
    metrics: FilehostCacheMetrics | None = None
    async with _FILEHOST_RESOURCE_LOCK:
        _evict_expired_resources_locked(now_ns)
        indexed = _FILEHOST_PATH_INDEX.get(resolved)
        if indexed is not None and indexed.revision == revision:
            url = _touch_mapping_locked(
                indexed.blob_key,
                suffix=_normalize_suffix(resolved.suffix),
                lease_id=lease_id,
                now_ns=now_ns,
            )
            if url is not None:
                _FILEHOST_COUNTERS.dedup_hits += 1
                cached_url = url
                metrics = _metrics_snapshot_locked()

    if cached_url is not None and metrics is not None:
        _emit_metrics("dedup", 1, metrics)
        return cached_url

    snapshot = await run_sync(_read_consistent_path_snapshot, resolved)
    return await _filehost_url_from_snapshot(snapshot, lease_id=lease_id)


async def _filehost_url_from_snapshot(
    snapshot: _ResourceSnapshot,
    *,
    lease_id: str | None,
) -> str:
    key = snapshot.key
    now_ns = time.time_ns()
    owner = False
    cached_metrics: FilehostCacheMetrics | None = None
    inflight: _InflightResourceUpload | None = None

    async with _FILEHOST_RESOURCE_LOCK:
        _evict_expired_resources_locked(now_ns)
        cached_url = _touch_mapping_locked(
            key,
            suffix=snapshot.suffix,
            lease_id=lease_id,
            now_ns=now_ns,
        )
        if cached_url is not None:
            _set_path_alias_locked(snapshot)
            _FILEHOST_COUNTERS.dedup_hits += 1
            cached_metrics = _metrics_snapshot_locked()

        if cached_url is None:
            inflight = _FILEHOST_RESOURCE_INFLIGHT.get(key)
            if (
                inflight is not None
                and snapshot.suffix
                and (inflight.suffix != snapshot.suffix)
            ):
                raise RuntimeError(
                    "Identical inflight filehost content was requested with "
                    "incompatible suffixes: "
                    f"{inflight.suffix or '<none>'!r} and {snapshot.suffix!r}."
                )
            if inflight is None:
                inflight = _InflightResourceUpload(
                    event=anyio.Event(),
                    suffix=snapshot.suffix,
                )
                _FILEHOST_RESOURCE_INFLIGHT[key] = inflight
                owner = True

    if cached_url is not None and cached_metrics is not None:
        _emit_metrics("dedup", 1, cached_metrics)
        return cached_url
    if inflight is None:
        raise RuntimeError("Filehost upload state was not initialized.")

    if not owner:
        await inflight.event.wait()
        if inflight.error is not None:
            raise inflight.error
        if inflight.url is None:
            raise RuntimeError("Filehost inflight upload completed without URL.")
        waiter_now_ns = time.time_ns()
        waiter_metrics: FilehostCacheMetrics | None = None
        async with _FILEHOST_RESOURCE_LOCK:
            cached_url = _touch_mapping_locked(
                key,
                suffix=snapshot.suffix,
                lease_id=lease_id,
                now_ns=waiter_now_ns,
            )
            if cached_url == inflight.url:
                _set_path_alias_locked(snapshot)
                _FILEHOST_COUNTERS.dedup_hits += 1
                waiter_metrics = _metrics_snapshot_locked()
        if waiter_metrics is not None:
            _emit_metrics("dedup", 1, waiter_metrics)
        return inflight.url

    try:
        url = (
            await _filehost_upload(snapshot.data, suffix=snapshot.suffix)
            if snapshot.suffix
            else await _filehost_upload(snapshot.data)
        )
        completed_at_ns = time.time_ns()
        mapping_expires_at_ns = _compute_mapping_expire_at(completed_at_ns)
        published_metrics: FilehostCacheMetrics | None = None
        with anyio.CancelScope(shield=True):
            async with _FILEHOST_RESOURCE_LOCK:
                current = _FILEHOST_RESOURCE_INFLIGHT.get(key)
                if current is not inflight:
                    raise RuntimeError(
                        "Filehost inflight upload ownership changed before publication."
                    )
                active_lease_count = sum(
                    key in lease_keys for lease_keys in _FILEHOST_LEASES.values()
                )
                _FILEHOST_RESOURCE_CACHE[key] = {
                    "url": url,
                    "digest": snapshot.digest,
                    "size": snapshot.size,
                    "hits": 1,
                    "last_access_ns": completed_at_ns,
                    "lease_ref_count": active_lease_count,
                    "mapping_expires_at_ns": (
                        None if active_lease_count else mapping_expires_at_ns
                    ),
                    "path_aliases": set(),
                    "suffix": snapshot.suffix,
                }
                if lease_id is not None:
                    _attach_key_to_lease_locked(lease_id, key)
                _set_path_alias_locked(snapshot)
                _FILEHOST_COUNTERS.uploaded_bytes += snapshot.size
                published_metrics = _metrics_snapshot_locked()
                inflight.url = url
                inflight.event.set()
                _FILEHOST_RESOURCE_INFLIGHT.pop(key, None)
        if published_metrics is not None:
            _emit_metrics("upload", snapshot.size, published_metrics)
        await checkpoint_if_cancelled()
        return url
    except BaseException as error:
        with anyio.CancelScope(shield=True):
            async with _FILEHOST_RESOURCE_LOCK:
                current = _FILEHOST_RESOURCE_INFLIGHT.get(key)
                if current is inflight:
                    inflight.error = (
                        error
                        if isinstance(error, Exception)
                        else RuntimeError("Filehost resource upload was cancelled.")
                    )
                    inflight.event.set()
                    _FILEHOST_RESOURCE_INFLIGHT.pop(key, None)
        raise


__all__ = [
    "FilehostCacheMetrics",
    "create_filehost_lease",
    "filehost_url",
    "get_filehost_cache_metrics",
    "prune_filehost_cache",
    "release_filehost_lease",
]
