from __future__ import annotations

from typing import TYPE_CHECKING, Any, ParamSpec, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from ipaddress import IPv4Address, IPv6Address
    from pathlib import Path

    from .config import ResourceStrategy
    from .models import (
        NotModified,
        PublishedResource,
        ResourceContent,
        ResourceRef,
        ResourceRevision,
    )
    from .templating import ExtensionSpec, FilterCallable, TemplateSource

R = TypeVar("R")
P = ParamSpec("P")


class ResourceReader(Protocol):
    async def read(
        self,
        reference: ResourceRef,
        *,
        refresh: bool = False,
    ) -> ResourceContent: ...

    async def read_conditional(
        self,
        reference: ResourceRef,
        revision: ResourceRevision,
    ) -> ResourceContent | NotModified:
        """Read only when the source moved past ``revision``.

        The caller supplies the revision it already holds; the reader maps
        it to a source-native conditional read (``If-None-Match`` /
        ``If-Modified-Since`` for HTTP, a stat compare for files) and
        returns :class:`NotModified` when the cached bytes are still
        current. Readers keep no validator state of their own.
        """
        ...

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

    async def publish(
        self,
        value: str | Path | bytes,
        *,
        lease_id: str | None = None,
        suffix: str | None = None,
    ) -> PublishedResource: ...

    async def startup(self) -> None: ...

    async def clear(self) -> None: ...

    async def aclose(self) -> None: ...


class WorkerExecutor(Protocol):
    async def run_sync(
        self,
        function: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R: ...


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
