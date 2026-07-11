"""Filehost infrastructure: URL generation, caching, auth guard, and prewarming.

This package is the public facade. All external consumers import from here;
internal implementation lives in the ``cache``, ``guard``, and ``warmup``
submodules.
"""

from __future__ import annotations

from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.resources.config import get_resource_config


def _enum_value(raw: object) -> str:
    """获取枚举值的字符串表示。"""
    return getattr(raw, "value", str(raw))


def _is_filehost_resolution_enabled() -> tuple[bool, str]:
    """检查 filehost 资源解析是否启用。"""
    cfg = get_resource_config()
    mode = _enum_value(cfg.resource_resolve_mode)
    remote_policy = _enum_value(cfg.remote_local_resource_policy)
    local_policy = _enum_value(cfg.local_local_resource_policy)
    status = f"mode={mode}, remote_policy={remote_policy}, local_policy={local_policy}"

    if mode == ResourceResolveMode.OFF.value:
        return False, status

    enabled = (
        remote_policy == RemoteLocalResourcePolicy.FILEHOST.value
        or local_policy == LocalLocalResourcePolicy.FILEHOST.value
    )
    return enabled, status


from .cache import (
    _FILEHOST_LEASES as _FILEHOST_LEASES,
)
from .cache import (
    _FILEHOST_PATH_INDEX as _FILEHOST_PATH_INDEX,
)
from .cache import (
    _FILEHOST_RESOURCE_CACHE as _FILEHOST_RESOURCE_CACHE,
)
from .cache import (
    _FILEHOST_RESOURCE_INFLIGHT as _FILEHOST_RESOURCE_INFLIGHT,
)
from .cache import (
    _FILEHOST_RESOURCE_LOCK as _FILEHOST_RESOURCE_LOCK,
)
from .cache import (
    FilehostCacheMetrics,
    create_filehost_lease,
    filehost_url,
    get_filehost_cache_metrics,
    prune_filehost_cache,
    release_filehost_lease,
)
from .cache import (
    _attach_key_to_lease_locked as _attach_key_to_lease_locked,
)
from .cache import (
    _cache_key as _cache_key,
)
from .cache import (
    _compute_expire_at as _compute_expire_at,
)
from .cache import (
    _evict_expired_resources_locked as _evict_expired_resources_locked,
)
from .cache import (
    _filehost_upload as _filehost_upload,
)
from .cache import (
    _filehost_url_from_path as _filehost_url_from_path,
)
from .cache import (
    _InflightResourceUpload as _InflightResourceUpload,
)
from .cache import (
    _normalize_and_snapshot_path as _normalize_and_snapshot_path,
)
from .cache import (
    _normalize_filehost_input as _normalize_filehost_input,
)
from .cache import (
    _stat_signature as _stat_signature,
)
from .cache import (
    _ttl_ns as _ttl_ns,
)
from .guard import (
    _FILEHOST_FALLBACK_INSTANCE_ID as _FILEHOST_FALLBACK_INSTANCE_ID,
)
from .guard import (
    _FILEHOST_GUARD_STATE as _FILEHOST_GUARD_STATE,
)
from .guard import (
    _derive_device_guard_token as _derive_device_guard_token,
)
from .guard import (
    _get_request_guard_header_config as _get_request_guard_header_config,
)
from .guard import (
    _is_valid_guard_token as _is_valid_guard_token,
)
from .guard import (
    _resolve_device_identifier as _resolve_device_identifier,
)
from .guard import (
    ensure_filehost_request_guard_installed,
    get_filehost_request_headers,
)
from .warmup import (
    _FILEHOST_PREWARM_LOCK as _FILEHOST_PREWARM_LOCK,
)
from .warmup import (
    _FILEHOST_PREWARM_PAYLOAD as _FILEHOST_PREWARM_PAYLOAD,
)
from .warmup import (
    _FILEHOST_PREWARM_STATE as _FILEHOST_PREWARM_STATE,
)
from .warmup import (
    _FILEHOST_REGISTERED_ROOTS as _FILEHOST_REGISTERED_ROOTS,
)
from .warmup import (
    _TEMPLATE_FILE_SUFFIXES as _TEMPLATE_FILE_SUFFIXES,
)
from .warmup import (
    _collect_prewarm_roots as _collect_prewarm_roots,
)
from .warmup import (
    _is_template_file as _is_template_file,
)
from .warmup import (
    _prewarm_enabled as _prewarm_enabled,
)
from .warmup import (
    _prewarm_resource_directories as _prewarm_resource_directories,
)
from .warmup import (
    _should_prewarm_path as _should_prewarm_path,
)
from .warmup import (
    ensure_filehost_plugin_loaded,
    ensure_filehost_runtime_ready,
    get_filehost_prewarm_status,
    register_filehost_resource_root,
)

__all__ = [
    "FilehostCacheMetrics",
    "create_filehost_lease",
    "ensure_filehost_plugin_loaded",
    "ensure_filehost_request_guard_installed",
    "ensure_filehost_runtime_ready",
    "filehost_url",
    "get_filehost_cache_metrics",
    "get_filehost_prewarm_status",
    "get_filehost_request_headers",
    "prune_filehost_cache",
    "register_filehost_resource_root",
    "release_filehost_lease",
]
