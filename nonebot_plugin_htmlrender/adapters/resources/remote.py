"""Policy-guarded remote resource transport.

The fetch loop enforces the injected :class:`RemoteAccessPolicy` on the
initial URL, on every DNS answer, and on every redirect hop.  Connections are
pinned to the address that passed validation, so a rebinding DNS server
cannot swap in a blocked address between the check and the connect.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from functools import partial
from http.client import HTTPConnection, HTTPSConnection
from ipaddress import IPv4Address, IPv6Address, ip_address
import socket
import ssl
import threading
import time
from typing import TYPE_CHECKING, TypeVar, final, overload
from urllib.parse import urljoin, urlsplit

import anyio
from anyio import from_thread
from anyio.lowlevel import EventLoopToken, current_token

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
    ResourceContent,
    ResourceRevision,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from nonebot_plugin_htmlrender.resources.models import RemoteResourceRef
    from nonebot_plugin_htmlrender.resources.ports import RemoteAccessPolicy

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ALLOWED_SCHEMES = frozenset({"http", "https"})

_T = TypeVar("_T")


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


class _TransportState(Enum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


_DRAIN_MARGIN_SECONDS = 0.5
_DEFAULT_SUBMISSION_BUDGET_SECONDS = 30.0


@dataclass(slots=True, eq=False)
class _AdmissionWaiter:
    """A caller waiting for an admission token, parked on its own backend."""

    wakeup: anyio.Event
    origin: EventLoopToken
    origin_thread: int
    granted: bool = False
    abandoned: bool = False
    closed: bool = False


@dataclass(slots=True, eq=False)
class _Submission:
    """A submitted hop whose completion is posted back to the origin backend."""

    completed: anyio.Event
    origin: EventLoopToken
    origin_thread: int
    abandoned: bool = False


@dataclass(slots=True, eq=False)
class _DrainWaiter:
    wakeup: anyio.Event
    origin: EventLoopToken
    origin_thread: int


@final
class RemoteTransportExecutor:
    """Run blocking remote-transport hops on a fixed, bounded thread pool.

    Admission is token-based: a caller acquires an instance-level token
    before its work is submitted, and the token is released only from the
    future's done callback. Cancelling the awaiting task abandons the wait
    but the pool worker keeps its slot until the socket work finishes, so
    repeated cancellations can never exceed the configured concurrency or
    build a second backlog inside the pool queue (worker count equals token
    count). Completion is posted back to the origin backend through its
    AnyIO event-loop token; the waiter awaits a plain ``anyio.Event`` and
    never occupies a default AnyIO worker thread.

    ``aclose()`` is stateful: it stops admission, cancels waiters that were
    not yet submitted, waits for in-flight work to drain within each
    submission's deadline, and only then shuts the pool down. A drain
    timeout raises :class:`ProviderLifecycleError` and leaves the executor
    in a retryable closing state.
    """

    def __init__(self, *, max_concurrent_fetches: int) -> None:
        if max_concurrent_fetches <= 0:
            raise ValueError("Remote fetch concurrency must be positive.")
        self._pool = ThreadPoolExecutor(
            max_workers=max_concurrent_fetches,
            thread_name_prefix="htmlrender-remote",
        )
        self._mutex = threading.Lock()
        self._state = _TransportState.OPEN
        self._tokens = max_concurrent_fetches
        self._admission: deque[_AdmissionWaiter] = deque()
        self._active: dict[_Submission, float] = {}
        self._drain: _DrainWaiter | None = None

    @staticmethod
    def _post(event: anyio.Event, origin: EventLoopToken, origin_thread: int) -> bool:
        """Set ``event`` on its owning backend; report delivery failure."""
        if threading.get_ident() == origin_thread:
            event.set()
            return True
        try:
            from_thread.run_sync(event.set, token=origin)
        except Exception:
            # The origin event loop is gone; the waiter can never resume.
            return False
        return True

    def _release_one_token(self) -> None:
        """Hand one admission token to the next viable waiter or bank it."""
        while True:
            with self._mutex:
                waiter: _AdmissionWaiter | None = None
                while self._admission:
                    candidate = self._admission.popleft()
                    if not candidate.abandoned:
                        waiter = candidate
                        break
                if waiter is None:
                    self._tokens += 1
                    return
                waiter.granted = True
            if self._post(waiter.wakeup, waiter.origin, waiter.origin_thread):
                return
            with self._mutex:
                waiter.abandoned = True

    def _notify_done(self, submission: _Submission) -> None:
        drain: _DrainWaiter | None = None
        notify: _Submission | None = None
        with self._mutex:
            self._active.pop(submission, None)
            if not submission.abandoned:
                notify = submission
            if self._state is _TransportState.CLOSING and not self._active:
                drain = self._drain
                self._drain = None
        self._release_one_token()
        if notify is not None:
            self._post(notify.completed, notify.origin, notify.origin_thread)
        if drain is not None:
            self._post(drain.wakeup, drain.origin, drain.origin_thread)

    async def run(
        self,
        function: Callable[[], _T],
        *,
        deadline: float | None = None,
    ) -> _T:
        """Run one blocking hop under admission control.

        ``deadline`` is the submission's monotonic completion bound; it is
        used by ``aclose()`` to bound the drain wait and defaults to a
        conservative budget when the caller supplies none.
        """
        origin = current_token()
        origin_thread = threading.get_ident()
        waiter: _AdmissionWaiter | None = None
        with self._mutex:
            if self._state is not _TransportState.OPEN:
                raise ResourceResolutionError("Remote transport executor is closed.")
            if self._tokens > 0:
                self._tokens -= 1
            else:
                waiter = _AdmissionWaiter(anyio.Event(), origin, origin_thread)
                self._admission.append(waiter)
        if waiter is not None:
            try:
                await waiter.wakeup.wait()
            except BaseException:
                with self._mutex:
                    granted = waiter.granted and not waiter.closed
                    waiter.abandoned = True
                if granted:
                    self._release_one_token()
                raise
            if waiter.closed:
                raise ResourceResolutionError(
                    "Remote transport executor closed while waiting for admission."
                )

        submission = _Submission(anyio.Event(), origin, origin_thread)
        submission_deadline = (
            deadline
            if deadline is not None
            else time.monotonic() + _DEFAULT_SUBMISSION_BUDGET_SECONDS
        )
        future: Future[_T] | None = None
        with self._mutex:
            if self._state is _TransportState.OPEN:
                future = self._pool.submit(function)
                self._active[submission] = submission_deadline
        if future is None:
            self._release_one_token()
            raise ResourceResolutionError("Remote transport executor is closed.")

        def _finish(done: Future[_T]) -> None:
            del done
            self._notify_done(submission)

        future.add_done_callback(_finish)

        try:
            await submission.completed.wait()
        except BaseException:
            # The result or exception is deliberately never consumed once
            # the waiter is gone; the done callback still releases the token.
            with self._mutex:
                submission.abandoned = True
            raise
        return future.result()

    async def aclose(self) -> None:
        """Stop admission, drain in-flight hops, then shut the pool down.

        Idempotent for every state; a drain timeout raises
        :class:`ProviderLifecycleError` and keeps the executor closing so a
        later ``aclose()`` can retry.
        """
        rejected: list[_AdmissionWaiter] = []
        drain: _DrainWaiter | None = None
        with self._mutex:
            if self._state is _TransportState.CLOSED:
                return
            self._state = _TransportState.CLOSING
            while self._admission:
                candidate = self._admission.popleft()
                if not candidate.abandoned:
                    candidate.closed = True
                    rejected.append(candidate)
            if self._active:
                if self._drain is None:
                    self._drain = _DrainWaiter(
                        anyio.Event(),
                        current_token(),
                        threading.get_ident(),
                    )
                drain = self._drain
            budget = max(
                (entry - time.monotonic() for entry in self._active.values()),
                default=0.0,
            )
        for waiter in rejected:
            self._post(waiter.wakeup, waiter.origin, waiter.origin_thread)
        if drain is not None:
            try:
                with anyio.fail_after(max(budget, 0.0) + _DRAIN_MARGIN_SECONDS):
                    await drain.wakeup.wait()
            except TimeoutError as error:
                with self._mutex:
                    if self._drain is drain:
                        self._drain = None
                    remaining = len(self._active)
                raise ProviderLifecycleError(
                    f"Remote transport close timed out with {remaining} "
                    "in-flight fetches still running; close may be retried.",
                    source=error,
                ) from error
        self._pool.shutdown(wait=True)
        with self._mutex:
            self._state = _TransportState.CLOSED


_REVISION_ETAG_PREFIX = "etag:"
_REVISION_MODIFIED_PREFIX = "modified:"


def _conditional_headers(revision: ResourceRevision | None) -> dict[str, str]:
    """Map a stored revision token back to its HTTP validator header."""
    if revision is None:
        return {}
    token = revision.token
    if token.startswith(_REVISION_ETAG_PREFIX):
        return {"If-None-Match": token[len(_REVISION_ETAG_PREFIX) :]}
    if token.startswith(_REVISION_MODIFIED_PREFIX):
        return {"If-Modified-Since": token[len(_REVISION_MODIFIED_PREFIX) :]}
    return {}


@dataclass(slots=True)
class _HopOutcome:
    """One request hop's result: redirect target, 304, or final content."""

    redirect_to: str | None = None
    content: ResourceContent | None = None
    not_modified: bool = False


def _read_response(
    connection: HTTPConnection,
    url: str,
    max_resource_bytes: int,
    *,
    conditional: bool = False,
) -> _HopOutcome:
    response = connection.getresponse()
    if response.status in _REDIRECT_STATUSES:
        location = response.getheader("Location")
        if not location:
            raise ResourceResolutionError(
                f"Remote redirect carries no Location header: {url}"
            )
        return _HopOutcome(redirect_to=urljoin(url, location))
    if conditional and response.status == 304:
        return _HopOutcome(not_modified=True)
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
    if etag:
        revision = ResourceRevision(f"{_REVISION_ETAG_PREFIX}{etag}")
    elif modified:
        revision = ResourceRevision(f"{_REVISION_MODIFIED_PREFIX}{modified}")
    else:
        revision = None
    return _HopOutcome(content=ResourceContent(data, media_type, revision))


def _perform_hop(
    url: str,
    *,
    pinned_addresses: tuple[IPv4Address | IPv6Address, ...],
    max_resource_bytes: int,
    socket_timeout: float,
    conditional_headers: Mapping[str, str] | None = None,
) -> _HopOutcome:
    """Connect to the first reachable authorized address and read one hop.

    Every candidate address has already passed the egress policy, so trying
    the next one when a connection fails keeps the SSRF guarantee while
    tolerating an unreachable first IPv6/IPv4 answer.
    """
    split = urlsplit(url)
    host = split.hostname
    if not host:
        raise ResourceResolutionError(f"Remote resource URL has no host: {url}")
    port = split.port or (443 if split.scheme == "https" else 80)
    last_error: OSError | None = None
    for address in pinned_addresses:
        connection = _open_connection(
            split.scheme,
            host,
            port,
            pinned_address=str(address),
            timeout=socket_timeout,
        )
        try:
            connection.request(
                "GET",
                _request_target(url),
                headers=dict(conditional_headers or {}),
            )
            return _read_response(
                connection,
                url,
                max_resource_bytes,
                conditional=bool(conditional_headers),
            )
        except OSError as error:
            # Connection/transport failure: fall back to the next authorized
            # address. Protocol-level failures raise from _read_response and
            # are not retried.
            last_error = error
            continue
        finally:
            connection.close()
    raise ResourceResolutionError(
        f"Remote host is unreachable at every authorized address: {url}",
        source=last_error,
    ) from last_error


@overload
async def read_remote(
    reference: RemoteResourceRef,
    *,
    policy: RemoteAccessPolicy,
    transport: RemoteTransportExecutor,
    max_resource_bytes: int,
    request_timeout_seconds: float = ...,
    conditional_revision: None = None,
) -> ResourceContent: ...


@overload
async def read_remote(
    reference: RemoteResourceRef,
    *,
    policy: RemoteAccessPolicy,
    transport: RemoteTransportExecutor,
    max_resource_bytes: int,
    request_timeout_seconds: float = ...,
    conditional_revision: ResourceRevision,
) -> ResourceContent | NotModified: ...


async def read_remote(
    reference: RemoteResourceRef,
    *,
    policy: RemoteAccessPolicy,
    transport: RemoteTransportExecutor,
    max_resource_bytes: int,
    request_timeout_seconds: float = 30.0,
    conditional_revision: ResourceRevision | None = None,
) -> ResourceContent | NotModified:
    """Fetch a remote resource under one end-to-end deadline.

    A single monotonic deadline covers DNS, every redirect and the body read;
    it is not reset per hop, and each socket's own timeout is the deadline's
    remaining budget. SSRF invariants hold on each hop: the URL, every DNS
    answer and each redirect are re-validated and the connection is pinned to
    an address that passed validation. When ``conditional_revision`` carries
    an HTTP validator, the request is conditional and a 304 response maps to
    :class:`NotModified`.
    """
    conditional_headers = _conditional_headers(conditional_revision)
    deadline = time.monotonic() + request_timeout_seconds
    try:
        with anyio.fail_after(request_timeout_seconds):
            url = reference.url
            for _ in range(policy.max_redirects + 1):
                policy.authorize_url(url)
                split = urlsplit(url)
                host = split.hostname
                if not host:
                    raise ResourceResolutionError(
                        f"Remote resource URL has no host: {url}"
                    )
                port = split.port or (443 if split.scheme == "https" else 80)
                addresses = await transport.run(
                    partial(_resolve_addresses, host, port),
                    deadline=deadline,
                )
                for address in addresses:
                    policy.authorize_address(url, address)
                remaining = max(0.05, deadline - time.monotonic())
                outcome = await transport.run(
                    partial(
                        _perform_hop,
                        url,
                        pinned_addresses=addresses,
                        max_resource_bytes=max_resource_bytes,
                        socket_timeout=remaining,
                        conditional_headers=conditional_headers,
                    ),
                    deadline=deadline,
                )
                if outcome.redirect_to is not None:
                    url = outcome.redirect_to
                    continue
                if outcome.not_modified:
                    if conditional_revision is None:
                        raise ResourceResolutionError(
                            f"Remote resource produced no content: {url}"
                        )
                    return NotModified(conditional_revision)
                if outcome.content is None:
                    raise ResourceResolutionError(
                        f"Remote resource produced no content: {url}"
                    )
                return outcome.content
    except TimeoutError as error:
        raise ResourceResolutionError(
            f"Remote resource fetch exceeded the {request_timeout_seconds}s deadline.",
            source=error,
        ) from error
    raise ResourceResolutionError(
        f"Remote resource exceeded {policy.max_redirects} redirects: {reference.url}"
    )


__all__ = [
    "ConfiguredRemoteAccessPolicy",
    "RemoteTransportExecutor",
    "read_bounded",
    "read_remote",
]
