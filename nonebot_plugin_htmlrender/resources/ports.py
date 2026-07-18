from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
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
    def resolve(
        self,
        value: object,
        *,
        template_base: Path | None = None,
    ) -> object: ...


__all__ = [
    "AssetPublisher",
    "LocalAccessPolicy",
    "ProviderResources",
    "ResourceReader",
    "ResourceResolver",
    "TemplateCompiler",
    "WorkerExecutor",
]
