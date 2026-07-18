from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from ipaddress import IPv4Address, IPv6Address
    from pathlib import Path

    from .config import ResourceStrategy
    from .models import ResourceContent, ResourceRef, ResourceRevision
    from .templating import ExtensionSpec, FilterCallable, TemplateSource

R = TypeVar("R")


class ResourceReader(Protocol):
    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent: ...

    async def revision(self, reference: ResourceRef) -> ResourceRevision | None: ...

    async def invalidate(self, reference: ResourceRef) -> None: ...

    async def clear(self) -> None: ...


class ProviderResources(Protocol):
    """Policy-bound resource operations available to engine providers."""

    @property
    def strategy(self) -> ResourceStrategy: ...

    def authorize_local(self, path: Path) -> Path: ...

    async def read_bytes(
        self,
        reference: str | Path | ResourceRef,
        *,
        refresh: bool = False,
    ) -> bytes: ...


class LocalAccessPolicy(Protocol):
    def authorize(self, path: Path) -> Path: ...


class RemoteAccessPolicy(Protocol):
    """Egress policy consulted before and during every remote fetch.

    ``authorize_address`` must be called with each resolved address and with
    every redirect hop so DNS answers cannot smuggle the request into a
    blocked network after the initial URL check passed.
    """

    @property
    def max_redirects(self) -> int: ...

    def authorize_url(self, url: str) -> None: ...

    def authorize_address(
        self,
        url: str,
        address: IPv4Address | IPv6Address,
    ) -> None: ...


class AssetPublisher(Protocol):
    def create_lease(self) -> str: ...

    async def release(self, lease_id: str) -> None: ...

    def request_headers(self) -> Mapping[str, str]: ...

    async def publish(
        self,
        value: str | Path | bytes,
        *,
        lease_id: str | None = None,
        suffix: str | None = None,
    ) -> str: ...

    async def startup(self) -> None: ...

    async def clear(self) -> None: ...

    async def aclose(self) -> None: ...


class WorkerExecutor(Protocol):
    async def run_sync(self, function: Callable[..., R], *args: object) -> R: ...


class TemplateCompiler(Protocol):
    async def render(
        self,
        template_path: TemplateSource,
        template_name: str,
        variables: Mapping[str, Any],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        immutable: bool = False,
        extensions: Sequence[ExtensionSpec] = (),
    ) -> str: ...

    async def clear(self) -> None: ...


class ResourceResolver(Protocol):
    """Custom per-call resolution hook accepted by the resource service.

    ``resolve`` may be synchronous or return an awaitable; the service awaits
    the result when needed.
    """

    def resolve(
        self,
        value: object,
        *,
        template_base: Path | None = None,
    ) -> object | Awaitable[object]: ...


__all__ = [
    "AssetPublisher",
    "LocalAccessPolicy",
    "ProviderResources",
    "RemoteAccessPolicy",
    "ResourceReader",
    "ResourceResolver",
    "TemplateCompiler",
    "WorkerExecutor",
]
