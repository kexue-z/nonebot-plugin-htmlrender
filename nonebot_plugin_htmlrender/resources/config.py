from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)


@dataclass(frozen=True)
class ResourceConfig:
    """Backend-agnostic configuration consumed by the resource resolution layer."""

    is_remote_mode: bool = False

    resource_resolve_mode: ResourceResolveMode = ResourceResolveMode.AUTO
    remote_local_resource_policy: RemoteLocalResourcePolicy = (
        RemoteLocalResourcePolicy.MEMORY
    )
    local_local_resource_policy: LocalLocalResourcePolicy = (
        LocalLocalResourcePolicy.FILE
    )

    filehost_allow_any_path: bool = False
    filehost_allowed_paths: tuple[Path, ...] = ()
    filehost_cache_ttl_seconds: float = 300.0
    filehost_prewarm_enabled: bool = True
    filehost_prewarm_max_files: int = 256
    filehost_prewarm_paths: tuple[Path, ...] = ()
    filehost_prewarm_extensions: tuple[str, ...] = ()
    filehost_request_header_name: str = "X-HTMLRender-Filehost-Request"
    filehost_request_header_value: str | None = None
    filehost_request_header_salt: str = "nonebot-plugin-htmlrender:filehost:guard:v1"


ResourceConfigProvider = Callable[[], ResourceConfig]

_config_provider: ResourceConfigProvider | None = None
_DEFAULT_CONFIG = ResourceConfig()


def register_resource_config_provider(provider: ResourceConfigProvider) -> None:
    """注册资源配置提供器。"""
    global _config_provider  # noqa: PLW0603
    _config_provider = provider


def get_resource_config() -> ResourceConfig:
    """获取当前资源配置。"""
    if _config_provider is not None:
        return _config_provider()
    return _DEFAULT_CONFIG


@dataclass(frozen=True)
class ResourceCacheSettings:
    """Sizing for the shared resource caches, injected by the composition root."""

    max_entries: int = 256
    max_bytes: int = 64 * 1024 * 1024
    revalidate_seconds: float = 1.0
    template_environment_max_entries: int = 64


ResourceCacheSettingsProvider = Callable[[], ResourceCacheSettings]

_cache_settings_provider: ResourceCacheSettingsProvider | None = None
_DEFAULT_CACHE_SETTINGS = ResourceCacheSettings()


def register_resource_cache_settings_provider(
    provider: ResourceCacheSettingsProvider | None,
) -> ResourceCacheSettingsProvider | None:
    """Install the cache sizing provider; returns the previous one."""
    global _cache_settings_provider  # noqa: PLW0603
    previous = _cache_settings_provider
    _cache_settings_provider = provider
    return previous


def get_resource_cache_settings() -> ResourceCacheSettings:
    """Return the composed cache sizing, falling back to defaults."""
    if _cache_settings_provider is not None:
        return _cache_settings_provider()
    return _DEFAULT_CACHE_SETTINGS


__all__ = [
    "ResourceCacheSettings",
    "ResourceCacheSettingsProvider",
    "ResourceConfig",
    "get_resource_cache_settings",
    "get_resource_config",
    "register_resource_cache_settings_provider",
    "register_resource_config_provider",
]
