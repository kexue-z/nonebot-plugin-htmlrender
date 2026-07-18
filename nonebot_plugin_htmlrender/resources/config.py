from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class ResourceResolveMode(str, Enum):
    """Whether document-local resources are resolved before execution."""

    OFF = "off"
    AUTO = "auto"
    STRICT = "strict"


class RemoteLocalResourcePolicy(str, Enum):
    """Transport used for local resources consumed by a remote provider."""

    MEMORY = "memory"
    PASSTHROUGH = "passthrough"
    FILEHOST = "filehost"
    ERROR = "error"


class LocalLocalResourcePolicy(str, Enum):
    """Transport used for local resources consumed by a local provider."""

    FILE = "file"
    FILEHOST = "filehost"
    PASSTHROUGH = "passthrough"


@dataclass(frozen=True, slots=True)
class ResourceCacheSettings:
    """Sizing for the shared resource caches, injected by the composition root."""

    max_entries: int = 256
    max_bytes: int = 64 * 1024 * 1024
    max_resource_bytes: int = 64 * 1024 * 1024
    revalidate_seconds: float = 1.0
    template_environment_max_entries: int = 64

    def __post_init__(self) -> None:
        if self.max_entries < 0 or self.max_bytes < 0 or self.max_resource_bytes < 0:
            raise ValueError("Resource cache limits must not be negative.")
        if self.revalidate_seconds < 0:
            raise ValueError(
                "Resource cache revalidation interval must not be negative."
            )
        if self.template_environment_max_entries < 0:
            raise ValueError("Template cache size must not be negative.")


@dataclass(frozen=True, slots=True)
class RemoteAccessSettings:
    """Network egress policy for remote resource fetches.

    Private, loopback, and link-local destinations are denied unless the host
    is explicitly listed in ``allow_hosts`` or ``allow_private_networks`` is
    enabled.  ``deny_hosts`` always wins over every allow rule.
    """

    allow_private_networks: bool = False
    allow_hosts: tuple[str, ...] = ()
    deny_hosts: tuple[str, ...] = ()
    max_redirects: int = 5

    def __post_init__(self) -> None:
        if self.max_redirects < 0:
            raise ValueError("Remote redirect limit must not be negative.")


@dataclass(frozen=True, slots=True)
class AssetPublisherSettings:
    cache_ttl_seconds: float = 300.0
    request_header_name: str = "X-HTMLRender-Filehost-Request"
    request_header_value: str | None = None
    request_header_salt: str = "nonebot-plugin-htmlrender:filehost:guard:v1"
    prewarm_enabled: bool = True
    prewarm_max_files: int = 256
    prewarm_paths: tuple[Path, ...] = ()
    prewarm_extensions: tuple[str, ...] = ()
    max_resource_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.cache_ttl_seconds < 0:
            raise ValueError("Publisher cache TTL must not be negative.")
        if self.prewarm_max_files < 0:
            raise ValueError("Publisher prewarm limit must not be negative.")
        if self.max_resource_bytes < 0:
            raise ValueError("Publisher resource size limit must not be negative.")
        if not self.request_header_name.strip():
            raise ValueError("Publisher request header name must not be empty.")


@dataclass(frozen=True, slots=True)
class ResourceStrategy:
    """Provider-selected resource transport expressed as immutable data."""

    is_remote: bool = False
    resolve_mode: ResourceResolveMode = ResourceResolveMode.AUTO
    remote_local_policy: RemoteLocalResourcePolicy = RemoteLocalResourcePolicy.MEMORY
    local_local_policy: LocalLocalResourcePolicy = LocalLocalResourcePolicy.FILE


__all__ = [
    "AssetPublisherSettings",
    "LocalLocalResourcePolicy",
    "RemoteAccessSettings",
    "RemoteLocalResourcePolicy",
    "ResourceCacheSettings",
    "ResourceResolveMode",
    "ResourceStrategy",
]
