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


__all__ = [
    "ResourceConfig",
    "get_resource_config",
    "register_resource_config_provider",
]
