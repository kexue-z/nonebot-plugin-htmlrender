"""SSRF regression coverage for the remote resource transport."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
import socket
import threading
import time
from typing import TYPE_CHECKING

import anyio
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from nonebot_plugin_htmlrender.adapters.resources.remote import (
    ConfiguredRemoteAccessPolicy,
    RemoteTransportExecutor,
    read_remote,
)
from nonebot_plugin_htmlrender.rendering.errors import ProviderLifecycleError
from nonebot_plugin_htmlrender.resources.config import RemoteAccessSettings
from nonebot_plugin_htmlrender.resources.errors import (
    ResourceAccessDenied,
    ResourceNotFound,
    ResourceResolutionError,
    ResourceSizeExceeded,
)
from nonebot_plugin_htmlrender.resources.models import (
    NotModified,
    RemoteResourceRef,
    ResourceRevision,
)


async def _wait_for(event: threading.Event) -> None:
    """Poll a pool-thread-owned event without borrowing a worker token."""
    with anyio.fail_after(1.0):
        while not event.is_set():  # noqa: ASYNC110
            await anyio.sleep(0.01)


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


def _transport() -> RemoteTransportExecutor:
    return RemoteTransportExecutor(max_concurrent_fetches=4)


@pytest.mark.anyio
async def test_dns_resolution_to_private_range_is_rejected_before_connecting(
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
        await read_remote(
            RemoteResourceRef("http://rebind.example.com/asset"),
            policy=ConfiguredRemoteAccessPolicy(),
            transport=_transport(),
            max_resource_bytes=1024,
        )


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        del format, args

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
        elif self.path == "/slow-redirect":
            time.sleep(0.06)
            self.send_response(302)
            self.send_header("Location", "/slow-redirect")
            self.end_headers()
        elif self.path == "/conditional":
            if self.headers.get("If-None-Match") == '"tag-1"':
                self.send_response(304)
                self.end_headers()
            else:
                body = b"conditional body"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("ETag", '"tag-1"')
                self.end_headers()
                self.wfile.write(body)
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


@pytest.mark.anyio
async def test_fetch_returns_content_from_allowed_host(loopback_server: str) -> None:
    content = await read_remote(
        RemoteResourceRef(f"{loopback_server}/ok"),
        policy=ConfiguredRemoteAccessPolicy(_LOOPBACK_ALLOWED),
        transport=_transport(),
        max_resource_bytes=1024,
    )

    assert content.data == b"remote body"
    assert content.media_type == "text/plain"
    assert content.revision is not None


@pytest.mark.anyio
async def test_redirect_into_private_range_is_blocked(loopback_server: str) -> None:
    with pytest.raises(ResourceAccessDenied):
        await read_remote(
            RemoteResourceRef(f"{loopback_server}/redirect-private"),
            policy=ConfiguredRemoteAccessPolicy(_LOOPBACK_ALLOWED),
            transport=_transport(),
            max_resource_bytes=1024,
        )


@pytest.mark.anyio
async def test_redirect_chain_is_bounded(loopback_server: str) -> None:
    policy = ConfiguredRemoteAccessPolicy(
        RemoteAccessSettings(allow_hosts=("127.0.0.1",), max_redirects=2)
    )

    with pytest.raises(ResourceResolutionError, match="redirects"):
        await read_remote(
            RemoteResourceRef(f"{loopback_server}/loop"),
            policy=policy,
            transport=_transport(),
            max_resource_bytes=1024,
        )


@pytest.mark.anyio
async def test_missing_remote_resource_maps_to_not_found(loopback_server: str) -> None:
    with pytest.raises(ResourceNotFound):
        await read_remote(
            RemoteResourceRef(f"{loopback_server}/missing"),
            policy=ConfiguredRemoteAccessPolicy(_LOOPBACK_ALLOWED),
            transport=_transport(),
            max_resource_bytes=1024,
        )


@pytest.mark.anyio
async def test_conditional_read_maps_validator_and_304(loopback_server: str) -> None:
    policy = ConfiguredRemoteAccessPolicy(_LOOPBACK_ALLOWED)
    transport = _transport()
    reference = RemoteResourceRef(f"{loopback_server}/conditional")

    first = await read_remote(
        reference,
        policy=policy,
        transport=transport,
        max_resource_bytes=1024,
    )
    assert first.data == b"conditional body"
    revision = first.revision
    assert revision is not None
    assert revision == ResourceRevision('etag:"tag-1"')

    second = await read_remote(
        reference,
        policy=policy,
        transport=transport,
        max_resource_bytes=1024,
        conditional_revision=revision,
    )
    assert second == NotModified(revision)


@pytest.mark.anyio
async def test_remote_read_respects_size_limit(loopback_server: str) -> None:
    with pytest.raises(ResourceSizeExceeded):
        await read_remote(
            RemoteResourceRef(f"{loopback_server}/big"),
            policy=ConfiguredRemoteAccessPolicy(_LOOPBACK_ALLOWED),
            transport=_transport(),
            max_resource_bytes=16,
        )


@pytest.mark.anyio
async def test_deadline_returns_control_promptly_on_slow_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slow_getaddrinfo(*args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        time.sleep(0.25)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", slow_getaddrinfo)

    with anyio.fail_after(0.05):
        with pytest.raises(ResourceResolutionError, match="deadline"):
            await read_remote(
                RemoteResourceRef("http://slow.example.com/asset"),
                policy=ConfiguredRemoteAccessPolicy(),
                transport=_transport(),
                max_resource_bytes=1024,
                request_timeout_seconds=0.02,
            )


@pytest.mark.anyio
async def test_concurrency_bound_survives_repeated_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow_getaddrinfo(*args: object, **kwargs: object) -> list[object]:
        nonlocal active, peak
        del args, kwargs
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.2)
        with lock:
            active -= 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", slow_getaddrinfo)
    transport = RemoteTransportExecutor(max_concurrent_fetches=1)

    # Eight fetches are each cancelled almost immediately. A CapacityLimiter
    # would be released on cancel and let all eight run at once; the thread
    # pool holds every slot until the blocking DNS call finishes.
    for _ in range(8):
        with anyio.move_on_after(0.01):
            await read_remote(
                RemoteResourceRef("http://slow.example.com/asset"),
                policy=ConfiguredRemoteAccessPolicy(),
                transport=transport,
                max_resource_bytes=1024,
            )
    await anyio.sleep(0.5)
    await transport.aclose()

    assert peak == 1


@pytest.mark.anyio
async def test_aclose_cancels_admission_waiters_and_rejects_new_runs() -> None:
    transport = RemoteTransportExecutor(max_concurrent_fetches=1)
    release = threading.Event()
    running = threading.Event()

    def blocked() -> None:
        running.set()
        release.wait(5.0)

    waiter_error: BaseException | None = None

    async def queued() -> None:
        nonlocal waiter_error
        try:
            await transport.run(lambda: None)
        except ResourceResolutionError as error:
            waiter_error = error

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(transport.run, blocked)
        await _wait_for(running)
        task_group.start_soon(queued)
        await anyio.sleep(0.05)
        release.set()
        await transport.aclose()

    assert isinstance(waiter_error, ResourceResolutionError)
    with pytest.raises(ResourceResolutionError, match="closed"):
        await transport.run(lambda: None)


@pytest.mark.anyio
async def test_aclose_drain_timeout_raises_and_close_stays_retryable() -> None:
    transport = RemoteTransportExecutor(max_concurrent_fetches=1)
    release = threading.Event()
    running = threading.Event()

    def blocked() -> None:
        running.set()
        release.wait(5.0)

    async def runner() -> None:
        await transport.run(blocked, deadline=time.monotonic() + 0.05)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(runner)
        await _wait_for(running)
        with pytest.raises(ProviderLifecycleError, match="in-flight"):
            await transport.aclose()
        release.set()
        await transport.aclose()
    await transport.aclose()


@pytest.mark.anyio
async def test_deadline_is_not_reset_by_redirect_hops(loopback_server: str) -> None:
    policy = ConfiguredRemoteAccessPolicy(
        RemoteAccessSettings(allow_hosts=("127.0.0.1",), max_redirects=50)
    )

    started = time.monotonic()
    with pytest.raises(ResourceResolutionError, match="deadline"):
        await read_remote(
            RemoteResourceRef(f"{loopback_server}/slow-redirect"),
            policy=policy,
            transport=_transport(),
            max_resource_bytes=1024,
            request_timeout_seconds=0.15,
        )
    assert time.monotonic() - started < 1.0
