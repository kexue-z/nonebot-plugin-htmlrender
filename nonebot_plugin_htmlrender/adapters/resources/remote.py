"""Policy-guarded remote resource transport.

The fetch loop enforces the injected :class:`RemoteAccessPolicy` on the
initial URL, on every DNS answer, and on every redirect hop.  Connections are
pinned to the address that passed validation, so a rebinding DNS server
cannot swap in a blocked address between the check and the connect.
"""

from __future__ import annotations

from http.client import HTTPConnection, HTTPSConnection
from ipaddress import IPv4Address, IPv6Address, ip_address
import socket
import ssl
from typing import TYPE_CHECKING, final
from urllib.parse import urljoin, urlsplit

from nonebot_plugin_htmlrender.resources.config import RemoteAccessSettings
from nonebot_plugin_htmlrender.resources.errors import (
    ResourceAccessDenied,
    ResourceNotFound,
    ResourceResolutionError,
    ResourceSizeExceeded,
)
from nonebot_plugin_htmlrender.resources.models import (
    ResourceContent,
    ResourceRevision,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from nonebot_plugin_htmlrender.resources.models import RemoteResourceRef
    from nonebot_plugin_htmlrender.resources.ports import RemoteAccessPolicy

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def read_bounded(read: Callable[[int], bytes], limit: int, label: str) -> bytes:
    data = read(-1 if limit == 0 else limit + 1)
    if limit > 0 and len(data) > limit:
        raise ResourceSizeExceeded(
            f"Resource {label} exceeds the configured {limit}-byte read limit."
        )
    return data


def _normalize_host(host: str) -> str:
    return host.lower().rstrip(".")


def _matches_host(host: str, patterns: Iterable[str]) -> bool:
    return any(host == entry or host.endswith(f".{entry}") for entry in patterns)


def _is_blocked_address(address: IPv4Address | IPv6Address) -> bool:
    if isinstance(address, IPv6Address):
        mapped = address.ipv4_mapped
        if mapped is not None:
            address = mapped
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


@final
class ConfiguredRemoteAccessPolicy:
    """Deny private-network egress unless a host is explicitly allowed."""

    def __init__(self, settings: RemoteAccessSettings | None = None) -> None:
        self._settings = settings or RemoteAccessSettings()
        self._allow_hosts = tuple(
            _normalize_host(entry) for entry in self._settings.allow_hosts
        )
        self._deny_hosts = tuple(
            _normalize_host(entry) for entry in self._settings.deny_hosts
        )

    @property
    def max_redirects(self) -> int:
        return self._settings.max_redirects

    def _host_of(self, url: str) -> str:
        split = urlsplit(url)
        if split.scheme not in _ALLOWED_SCHEMES:
            raise ResourceAccessDenied(
                f"Remote resource scheme {split.scheme!r} is not allowed: {url}"
            )
        host = split.hostname
        if not host:
            raise ResourceAccessDenied(f"Remote resource URL has no host: {url}")
        return _normalize_host(host)

    def authorize_url(self, url: str) -> None:
        host = self._host_of(url)
        if _matches_host(host, self._deny_hosts):
            raise ResourceAccessDenied(f"Remote host {host!r} is denied: {url}")
        if _matches_host(host, self._allow_hosts):
            return
        try:
            literal = ip_address(host)
        except ValueError:
            return
        self._check_address(url, literal)

    def authorize_address(
        self,
        url: str,
        address: IPv4Address | IPv6Address,
    ) -> None:
        host = self._host_of(url)
        if _matches_host(host, self._deny_hosts):
            raise ResourceAccessDenied(f"Remote host {host!r} is denied: {url}")
        if _matches_host(host, self._allow_hosts):
            return
        self._check_address(url, address)

    def _check_address(self, url: str, address: IPv4Address | IPv6Address) -> None:
        if self._settings.allow_private_networks:
            return
        if _is_blocked_address(address):
            raise ResourceAccessDenied(
                f"Remote resource resolves to blocked address {address}: {url}"
            )


@final
class _PinnedHTTPConnection(HTTPConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        pinned_address: str,
        timeout: float,
    ) -> None:
        super().__init__(host, port, timeout=timeout)
        self._pinned_address = pinned_address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
        )


@final
class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        pinned_address: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._pinned_address = pinned_address
        self._ssl_context = context

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
        )
        # SNI and certificate validation stay bound to the original hostname
        # while the transport connects to the pre-validated address.
        self.sock = self._ssl_context.wrap_socket(raw, server_hostname=self.host)


def _resolve_addresses(
    host: str,
    port: int,
) -> tuple[IPv4Address | IPv6Address, ...]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses: list[IPv4Address | IPv6Address] = []
    seen: set[str] = set()
    for info in infos:
        raw = str(info[4][0])
        if raw in seen:
            continue
        seen.add(raw)
        addresses.append(ip_address(raw.split("%", 1)[0]))
    if not addresses:
        raise ResourceResolutionError(f"Remote host did not resolve: {host}")
    return tuple(addresses)


def _open_connection(
    scheme: str,
    host: str,
    port: int,
    *,
    pinned_address: str,
    timeout: float,
) -> HTTPConnection:
    if scheme == "https":
        return _PinnedHTTPSConnection(
            host,
            port,
            pinned_address=pinned_address,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    return _PinnedHTTPConnection(
        host,
        port,
        pinned_address=pinned_address,
        timeout=timeout,
    )


def _request_target(url: str) -> str:
    split = urlsplit(url)
    target = split.path or "/"
    if split.query:
        target = f"{target}?{split.query}"
    return target


def read_remote(
    reference: RemoteResourceRef,
    *,
    policy: RemoteAccessPolicy,
    max_resource_bytes: int,
    timeout: float = 30.0,
) -> ResourceContent:
    url = reference.url
    for _ in range(policy.max_redirects + 1):
        policy.authorize_url(url)
        split = urlsplit(url)
        host = split.hostname
        if not host:
            raise ResourceResolutionError(f"Remote resource URL has no host: {url}")
        port = split.port or (443 if split.scheme == "https" else 80)
        addresses = _resolve_addresses(host, port)
        for address in addresses:
            policy.authorize_address(url, address)

        connection = _open_connection(
            split.scheme,
            host,
            port,
            pinned_address=str(addresses[0]),
            timeout=timeout,
        )
        try:
            connection.request("GET", _request_target(url))
            response = connection.getresponse()
            if response.status in _REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise ResourceResolutionError(
                        f"Remote redirect carries no Location header: {url}"
                    )
                url = urljoin(url, location)
                continue
            if response.status == 404:
                raise ResourceNotFound(f"Remote resource was not found: {url}")
            if response.status >= 400:
                raise ResourceResolutionError(
                    f"Remote resource request failed with HTTP {response.status}: {url}"
                )
            content_length = response.getheader("Content-Length")
            if (
                max_resource_bytes > 0
                and content_length is not None
                and content_length.isdigit()
                and int(content_length) > max_resource_bytes
            ):
                raise ResourceSizeExceeded(
                    f"Resource {url} exceeds the configured "
                    f"{max_resource_bytes}-byte read limit."
                )
            data = read_bounded(response.read, max_resource_bytes, url)
            media_type = response.headers.get_content_type()
            etag = response.getheader("ETag")
            modified = response.getheader("Last-Modified")
        finally:
            connection.close()
        revision_token = etag or modified
        revision = ResourceRevision(revision_token) if revision_token else None
        return ResourceContent(data, media_type, revision)
    raise ResourceResolutionError(
        f"Remote resource exceeded {policy.max_redirects} redirects: {reference.url}"
    )


__all__ = [
    "ConfiguredRemoteAccessPolicy",
    "read_bounded",
    "read_remote",
]
