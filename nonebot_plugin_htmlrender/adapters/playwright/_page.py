"""Page context lifecycle and network helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Protocol, final
from urllib.parse import urlsplit, urlunsplit

import anyio
from nonebot.log import logger
from playwright.async_api import Browser, Page, Route

from nonebot_plugin_htmlrender.capabilities.playwright import _page_signature
from nonebot_plugin_htmlrender.resources.headers import merge_request_headers

from .telemetry import detach_page, instrument_page

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from .render import PlaywrightLease


class _ConsoleEvent(Protocol):
    @property
    def type(self) -> str: ...


class _RequestEvent(Protocol):
    @property
    def method(self) -> str: ...

    @property
    def resource_type(self) -> str: ...


class _ResponseEvent(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def request(self) -> _RequestEvent: ...


@final
class PageContext:
    """Open and instrument pages from one injected Playwright lease."""

    def __init__(self, lease: PlaywrightLease) -> None:
        self._lease = lease

    @_page_signature
    @asynccontextmanager
    async def open(self, **kwargs: Any) -> AsyncIterator[Page]:
        browser = self._lease.browser
        if not isinstance(browser, Browser):
            raise RuntimeError("Playwright lease does not expose a Browser.")
        page = await browser.new_page(**kwargs)
        instrument_page(page, page_name="render_context")
        try:
            yield page
        finally:
            try:
                with anyio.CancelScope(shield=True):
                    await page.close()
            finally:
                detach_page(page)


def log_console_event(message: _ConsoleEvent) -> None:
    """Log only the console event type; console text is untrusted payload."""
    logger.debug(f"Browser console event: type={message.type}")


def log_page_error_event(_error: object) -> None:
    """Log a page error without its message, which is untrusted payload."""
    logger.warning("Page raised an uncaught error.")


def log_request_failed_event(request: _RequestEvent) -> None:
    """Log only stable request fields; the URL is untrusted payload."""
    logger.warning(
        "Playwright request failed: "
        f"method={request.method}, resource_type={request.resource_type}"
    )


def log_response_event(response: _ResponseEvent) -> None:
    """Log only the status and resource type for failed image/document loads."""
    if response.status >= 400 and response.request.resource_type in {
        "image",
        "document",
    }:
        logger.warning(
            "Playwright response error: "
            f"status={response.status}, "
            f"resource_type={response.request.resource_type}"
        )


def _setup_page_logging(page: Page) -> None:
    """Log only stable page events; page content is untrusted.

    Console text, page-error messages, request URLs and Playwright failure
    detail can all carry attacker-controlled payload, so only the stable
    event type, HTTP method, resource type and status code are recorded.
    """
    page.on("console", log_console_event)
    page.on("pageerror", log_page_error_event)
    page.on("requestfailed", log_request_failed_event)
    page.on("response", log_response_event)


def _normalize_request_url(url: str) -> str:
    """Canonical identity for matching a request against published URLs.

    Mirrors the publisher-side normalization: scheme/host case, default port
    and fragment only. Path and query stay significant, so a different query
    or a redirect target never matches another resource's authorization.
    """
    split = urlsplit(url)
    scheme = split.scheme.lower()
    host = (split.hostname or "").lower()
    default_port = {"http": 80, "https": 443}.get(scheme)
    port = split.port
    netloc = host if port is None or port == default_port else f"{host}:{port}"
    return urlunsplit((scheme, netloc, split.path, split.query, ""))


async def install_filehost_request_route(
    page: Page,
    *,
    authorization: Mapping[str, Mapping[str, str]],
) -> None:
    """Inject each publication's headers only on its exact published URL.

    ``authorization`` maps a normalized published URL to the request headers
    it was published with. A request is authorized only when its normalized
    URL matches exactly; host, path prefix or network location never widen
    the scope. The authorized request is fetched with ``max_redirects=0`` and
    fulfilled directly, so Playwright never carries the authorization header
    onto a browser-followed redirect: that redirect re-enters this handler as
    a fresh, unauthorized request.
    """
    if not authorization:
        return

    async def _route_handler(route: Route) -> None:
        request = route.request
        headers = authorization.get(_normalize_request_url(request.url))
        if headers:
            # The published capability is authoritative: it overrides any
            # caller-preset value for the same header instead of letting a
            # wrong preset win via setdefault-style merging.
            merged_headers = merge_request_headers(request.headers, headers)
            response = await route.fetch(headers=merged_headers, max_redirects=0)
            await route.fulfill(response=response)
            return
        await route.continue_()

    await page.route("**/*", _route_handler)


__all__ = [
    "PageContext",
    "install_filehost_request_route",
]
