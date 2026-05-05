"""Filehost URL generation, LRU cache, and lease management."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from io import BytesIO
from pathlib import Path
import time
from typing import TypedDict
import uuid

import anyio
from anyio.to_thread import run_sync

from nonebot_plugin_htmlrender.resources.config import get_resource_config

FilehostInput = Path | bytes | bytearray | BytesIO | str


class _CacheEntry(TypedDict):
    """filehost 资源缓存的单条条目结构。"""

    url: str
    mtime_ns: int
    size: int
    hits: int
    last_access_ns: int
    lease_ref_count: int
    expires_at_ns: int | None


_FILEHOST_RESOURCE_LOCK = anyio.Lock()
_FILEHOST_RESOURCE_CACHE: dict[str, _CacheEntry] = {}
_FILEHOST_LEASES: dict[str, set[str]] = {}


@dataclass
class _InflightResourceUpload:
    """正在上传的 filehost 资源占位项。

    多个并发请求需要等待同一资源完成上传时，通过共享 ``event`` 协调，
    上传完成后再读取 ``url`` 或 ``error``。
    """

    event: anyio.Event
    url: str | None = None
    error: Exception | None = None


_FILEHOST_RESOURCE_INFLIGHT: dict[str, _InflightResourceUpload] = {}


def _normalize_filehost_input(value: FilehostInput) -> Path | bytes | str:
    """规范化 filehost 输入到统一类型。"""
    if isinstance(value, Path):
        return value.expanduser().resolve()
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, BytesIO):
        return value.getvalue()
    return value


def _stat_signature(path: Path) -> tuple[int, int]:
    """获取文件的修改时间和大小签名。"""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _cache_key(path: Path) -> str:
    """生成文件路径的缓存键。"""
    return str(path.resolve())


def _normalize_and_snapshot_path(path: Path) -> tuple[Path, str, int, int]:
    """规范化路径并获取文件快照信息。"""
    resolved = path.expanduser().resolve()
    key = _cache_key(resolved)
    mtime_ns, size = _stat_signature(resolved)
    return resolved, key, mtime_ns, size


async def _normalize_and_snapshot_path_async(path: Path) -> tuple[Path, str, int, int]:
    """异步规范化路径并获取文件快照信息。"""
    return await run_sync(_normalize_and_snapshot_path, path)


def _ttl_ns() -> int:
    """获取缓存 TTL 的纳秒值。"""
    cfg = get_resource_config()
    ttl = float(cfg.filehost_cache_ttl_seconds)
    return int(ttl * 1_000_000_000)


def _compute_expire_at(now_ns: int) -> int:
    """计算缓存条目的过期时间戳（纳秒）。"""
    return now_ns + _ttl_ns()


def _evict_expired_resources_locked(now_ns: int) -> None:
    """清除过期且无租约引用的缓存条目（需持锁调用）。"""
    expired_keys = [
        key
        for key, entry in _FILEHOST_RESOURCE_CACHE.items()
        if (expires_at_ns := entry["expires_at_ns"]) is not None
        if entry["lease_ref_count"] <= 0 and expires_at_ns <= now_ns
    ]
    for key in expired_keys:
        _FILEHOST_RESOURCE_CACHE.pop(key, None)


def _attach_key_to_lease_locked(lease_id: str, key: str) -> None:
    """将缓存键关联到租约并增加引用计数（需持锁调用）。"""
    lease_keys = _FILEHOST_LEASES.setdefault(lease_id, set())
    if key in lease_keys:
        return
    lease_keys.add(key)
    entry = _FILEHOST_RESOURCE_CACHE.get(key)
    if entry is None:
        return
    entry["lease_ref_count"] = int(entry.get("lease_ref_count", 0)) + 1
    entry["expires_at_ns"] = None


def create_filehost_lease() -> str:
    """创建新的 filehost 资源租约。"""
    lease_id = f"lease:{uuid.uuid4().hex}"
    _FILEHOST_LEASES.setdefault(lease_id, set())
    return lease_id


async def release_filehost_lease(lease_id: str) -> None:
    """释放 filehost 资源租约，减少引用计数并设置过期时间。

    Args:
        lease_id: 要释放的租约标识。
    """
    now_ns = time.time_ns()
    async with _FILEHOST_RESOURCE_LOCK:
        lease_keys = _FILEHOST_LEASES.pop(lease_id, set())
        for key in lease_keys:
            entry = _FILEHOST_RESOURCE_CACHE.get(key)
            if entry is None:
                continue
            ref_count = max(0, int(entry.get("lease_ref_count", 0)) - 1)
            entry["lease_ref_count"] = ref_count
            if ref_count == 0:
                entry["expires_at_ns"] = _compute_expire_at(now_ns)
        _evict_expired_resources_locked(now_ns)


async def prune_filehost_cache() -> None:
    """清理过期的 filehost 缓存条目。"""
    now_ns = time.time_ns()
    async with _FILEHOST_RESOURCE_LOCK:
        _evict_expired_resources_locked(now_ns)


async def filehost_url(value: FilehostInput, *, lease_id: str | None = None) -> str:
    """获取资源的 filehost URL。

    Args:
        value: 文件路径、字节数据或字符串形式的资源。
        lease_id: 可选的租约标识，关联后资源在租约存续期间不会过期。

    Returns:
        资源对应的 filehost URL。
    """
    normalized = _normalize_filehost_input(value)
    if isinstance(normalized, Path):
        return await _filehost_url_from_path(normalized, lease_id=lease_id)
    return await _filehost_upload(normalized)


async def _filehost_upload(value: FilehostInput) -> str:
    """上传资源到 filehost 服务并返回 URL。"""
    try:
        module = import_module("nonebot_plugin_filehost")
        file_host_cls = module.FileHost
    except Exception as e:
        raise RuntimeError(
            "nonebot-plugin-filehost is required for filehost resource resolution."
        ) from e

    if isinstance(value, bytearray):
        value = bytes(value)
    url = await file_host_cls(value).to_url()
    return str(url)


async def _filehost_url_from_path(path: Path, *, lease_id: str | None = None) -> str:
    """从文件路径获取 filehost URL，带缓存和并发上传去重。"""
    resolved, key, mtime_ns, size = await _normalize_and_snapshot_path_async(path)
    inflight: _InflightResourceUpload | None = None
    owner = False
    now_ns = time.time_ns()

    async with _FILEHOST_RESOURCE_LOCK:
        _evict_expired_resources_locked(now_ns)
        cached = _FILEHOST_RESOURCE_CACHE.get(key)
        if (
            cached is not None
            and cached["mtime_ns"] == mtime_ns
            and cached["size"] == size
        ):
            cached["hits"] = int(cached["hits"]) + 1
            cached["last_access_ns"] = now_ns
            if lease_id is not None:
                _attach_key_to_lease_locked(lease_id, key)
            elif int(cached.get("lease_ref_count", 0)) <= 0:
                cached["expires_at_ns"] = _compute_expire_at(now_ns)
            return str(cached["url"])

        existing = _FILEHOST_RESOURCE_INFLIGHT.get(key)
        if existing is not None:
            inflight = existing
        else:
            inflight = _InflightResourceUpload(event=anyio.Event())
            _FILEHOST_RESOURCE_INFLIGHT[key] = inflight
            owner = True

    if not owner:
        assert inflight is not None
        await inflight.event.wait()
        if inflight.error is not None:
            raise inflight.error
        if inflight.url is None:
            raise RuntimeError("Filehost inflight upload completed without URL.")
        return inflight.url

    try:
        url = await _filehost_upload(resolved)
    except Exception as e:
        async with _FILEHOST_RESOURCE_LOCK:
            current = _FILEHOST_RESOURCE_INFLIGHT.pop(key, None)
            if current is inflight:
                inflight.error = e
                inflight.event.set()
        raise

    async with _FILEHOST_RESOURCE_LOCK:
        _FILEHOST_RESOURCE_CACHE[key] = {
            "url": url,
            "mtime_ns": mtime_ns,
            "size": size,
            "hits": 1,
            "last_access_ns": now_ns,
            "lease_ref_count": 0,
            "expires_at_ns": _compute_expire_at(now_ns),
        }
        if lease_id is not None:
            _attach_key_to_lease_locked(lease_id, key)
        current = _FILEHOST_RESOURCE_INFLIGHT.pop(key, None)
        if current is inflight:
            inflight.url = url
            inflight.event.set()
    return url
