"""SSRF regression coverage for the remote resource transport."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
import socket
import threading
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from nonebot_plugin_htmlrender.adapters.resources.remote import (
    ConfiguredRemoteAccessPolicy,
    read_remote,
)
from nonebot_plugin_htmlrender.resources.config import RemoteAccessSettings
from nonebot_plugin_htmlrender.resources.errors import (
    ResourceAccessDenied,
    ResourceNotFound,
    ResourceResolutionError,
    ResourceSizeExceeded,
)
from nonebot_plugin_htmlrender.resources.models import RemoteResourceRef


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1/secret",
        "http://10.0.0.8/internal",
        "http://192.168.1.1/router",
        "http://[::1]/secret",
        "http://0.0.0.0/",
    ],
)
def test_default_policy_denies_private_address_literals(url: str) -> None:
    policy = ConfiguredRemoteAccessPolicy()

    with pytest.raises(ResourceAccessDenied):
        policy.authorize_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://93.184.216.34/",
        "https://example.com/asset.png",
    ],
)
def test_default_policy_allows_public_destinations(url: str) -> None:
    ConfiguredRemoteAccessPolicy().authorize_url(url)


@pytest.mark.parametrize("scheme", ["file", "ftp", "gopher", "data"])
def test_policy_rejects_non_http_schemes(scheme: str) -> None:
    with pytest.raises(ResourceAccessDenied):
        ConfiguredRemoteAccessPolicy().authorize_url(f"{scheme}://example.com/x")


def test_policy_denies_dns_answers_in_private_ranges() -> None:
    policy = ConfiguredRemoteAccessPolicy()
    url = "http://rebind.example.com/asset"

    policy.authorize_url(url)
    with pytest.raises(ResourceAccessDenied):
        policy.authorize_address(url, ip_address("10.0.0.1"))
    with pytest.raises(ResourceAccessDenied):
        policy.authorize_address(url, ip_address("169.254.169.254"))
    policy.authorize_address(url, ip_address("93.184.216.34"))


def test_allow_hosts_whitelists_private_destinations_including_subdomains() -> None:
    policy = ConfiguredRemoteAccessPolicy(
        RemoteAccessSettings(allow_hosts=("internal.test",))
    )

    policy.authorize_address("http://internal.test/asset", ip_address("10.0.0.1"))
    policy.authorize_address("http://cdn.internal.test/asset", ip_address("10.0.0.1"))
    with pytest.raises(ResourceAccessDenied):
        policy.authorize_address("http://other.test/asset", ip_address("10.0.0.1"))


def test_deny_hosts_wins_over_public_and_allowed_hosts() -> None:
    policy = ConfiguredRemoteAccessPolicy(
        RemoteAccessSettings(
            allow_hosts=("blocked.test",),
            deny_hosts=("blocked.test",),
        )
    )

    with pytest.raises(ResourceAccessDenied):
        policy.authorize_url("https://blocked.test/asset")
    with pytest.raises(ResourceAccessDenied):
        policy.authorize_url("https://sub.blocked.test/asset")


def test_allow_private_networks_opts_out_of_blocking() -> None:
    policy = ConfiguredRemoteAccessPolicy(
        RemoteAccessSettings(allow_private_networks=True)
    )

    policy.authorize_url("http://127.0.0.1/asset")
    policy.authorize_address("http://a.test/x", ip_address("10.0.0.1"))


def test_dns_resolution_to_private_range_is_rejected_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.13.37.1", 80)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    def failing_connection(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("must not connect to a blocked address")

    monkeypatch.setattr(socket, "create_connection", failing_connection)

    with pytest.raises(ResourceAccessDenied):
        read_remote(
            RemoteResourceRef("http://rebind.example.com/asset"),
            policy=ConfiguredRemoteAccessPolicy(),
            max_resource_bytes=1024,
        )


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        del fmt, args

    def do_GET(self) -> None:
        if self.path == "/ok":
            body = b"remote body"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", '"tag-1"')
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect-private":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
        elif self.path == "/big":
            body = b"x" * 64
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def loopback_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


_LOOPBACK_ALLOWED = RemoteAccessSettings(allow_hosts=("127.0.0.1",))


def test_fetch_returns_content_from_allowed_host(loopback_server: str) -> None:
    content = read_remote(
        RemoteResourceRef(f"{loopback_server}/ok"),
        policy=ConfiguredRemoteAccessPolicy(_LOOPBACK_ALLOWED),
        max_resource_bytes=1024,
    )

    assert content.data == b"remote body"
    assert content.media_type == "text/plain"
    assert content.revision is not None


def test_redirect_into_private_range_is_blocked(loopback_server: str) -> None:
    with pytest.raises(ResourceAccessDenied):
        read_remote(
            RemoteResourceRef(f"{loopback_server}/redirect-private"),
            policy=ConfiguredRemoteAccessPolicy(_LOOPBACK_ALLOWED),
            max_resource_bytes=1024,
        )


def test_redirect_chain_is_bounded(loopback_server: str) -> None:
    policy = ConfiguredRemoteAccessPolicy(
        RemoteAccessSettings(allow_hosts=("127.0.0.1",), max_redirects=2)
    )

    with pytest.raises(ResourceResolutionError, match="redirects"):
        read_remote(
            RemoteResourceRef(f"{loopback_server}/loop"),
            policy=policy,
            max_resource_bytes=1024,
        )


def test_missing_remote_resource_maps_to_not_found(loopback_server: str) -> None:
    with pytest.raises(ResourceNotFound):
        read_remote(
            RemoteResourceRef(f"{loopback_server}/missing"),
            policy=ConfiguredRemoteAccessPolicy(_LOOPBACK_ALLOWED),
            max_resource_bytes=1024,
        )


def test_remote_read_respects_size_limit(loopback_server: str) -> None:
    with pytest.raises(ResourceSizeExceeded):
        read_remote(
            RemoteResourceRef(f"{loopback_server}/big"),
            policy=ConfiguredRemoteAccessPolicy(_LOOPBACK_ALLOWED),
            max_resource_bytes=16,
        )
