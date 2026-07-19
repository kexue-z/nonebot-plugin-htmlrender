from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Generic, TypeAlias, TypeVar
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Mapping

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PublishedResource:
    """A published asset URL bundled with the exact request authorization.

    ``request_headers`` are the headers a consumer must send to fetch this
    specific URL. The authorization travels with the URL so callers never
    infer it from host, path prefix or network location.
    """

    url: str
    request_headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_headers",
            MappingProxyType(dict(self.request_headers)),
        )


@dataclass(frozen=True, slots=True)
class ResourceResolution(Generic[T]):
    """A resolved value bundled with exact per-URL request authorization.

    ``request_headers_by_url`` is intentionally keyed by the resolved URL
    instead of a host or path prefix. Consumers must apply each header set
    only to the matching URL.
    """

    value: T
    request_headers_by_url: Mapping[str, Mapping[str, str]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        frozen_headers = {
            url: MappingProxyType(dict(headers))
            for url, headers in sorted(self.request_headers_by_url.items())
        }
        object.__setattr__(
            self,
            "request_headers_by_url",
            MappingProxyType(frozen_headers),
        )


@dataclass(frozen=True, slots=True)
class ResourceRevision:
    """Opaque source revision used by caching readers."""

    token: str


@dataclass(frozen=True, slots=True)
class ResourceContent:
    """One immutable resource snapshot."""

    data: bytes
    media_type: str | None = None
    revision: ResourceRevision | None = None


@dataclass(frozen=True, slots=True)
class NotModified:
    """Typed conditional-read outcome: the cached revision is still current."""

    revision: ResourceRevision


@dataclass(frozen=True, slots=True)
class FileResourceRef:
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", self.path.expanduser().resolve())

    @property
    def cache_key(self) -> tuple[str, str]:
        return ("file", str(self.path))


@dataclass(frozen=True, slots=True)
class PackageResourceRef:
    package: str
    name: str

    def __post_init__(self) -> None:
        logical = PurePosixPath(self.name)
        if (
            not logical.parts
            or logical.is_absolute()
            or any(part in {"", ".", ".."} for part in logical.parts)
        ):
            raise ValueError(f"Invalid logical resource name: {self.name!r}")
        object.__setattr__(self, "name", logical.as_posix())

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return ("package", self.package, self.name)


@dataclass(frozen=True, slots=True)
class RemoteResourceRef:
    url: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "Remote resources must use an absolute http:// or https:// URL."
            )

    @property
    def cache_key(self) -> tuple[str, str]:
        return ("remote", self.url)


@dataclass(frozen=True, slots=True)
class InlineResourceRef:
    data: bytes
    media_type: str | None = None
    _digest: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise TypeError("Inline resource data must be immutable bytes.")
        object.__setattr__(self, "_digest", sha256(self.data).digest())

    @property
    def digest(self) -> str:
        return self._digest.hex()

    @property
    def cache_key(self) -> tuple[str, bytes, int, str | None]:
        return ("inline", self._digest, len(self.data), self.media_type)


ResourceRef: TypeAlias = (
    FileResourceRef | PackageResourceRef | RemoteResourceRef | InlineResourceRef
)


__all__ = [
    "FileResourceRef",
    "InlineResourceRef",
    "NotModified",
    "PackageResourceRef",
    "PublishedResource",
    "RemoteResourceRef",
    "ResourceContent",
    "ResourceRef",
    "ResourceResolution",
    "ResourceRevision",
]
