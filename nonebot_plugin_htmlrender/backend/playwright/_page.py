"""Page context lifecycle, network helpers, and PNA safety checks."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
import ipaddress
from typing import AsyncContextManager, Protocol, runtime_checkable
from typing_extensions import Unpack
from urllib.parse import urlparse, urlsplit, urlunsplit

from nonebot.log import logger
from playwright.async_api import Browser, Page, Route

from .telemetry import detach_page, instrument_page
from .types import PageContextKwargs

RenderContextProvider = Callable[..., AsyncContextManager[object]]

_render_context_state: dict[str, RenderContextProvider | None] = {"provider": None}


@runtime_checkable
class SupportsBrowserSession(Protocol):
    """声明持有浏览器句柄的会话协议。

    用于运行时校验：任意会话只要暴露 ``handle`` 字段并指向 Playwright Browser，
    即可作为打开页面上下文的来源。
    """

    handle: object


def _as_page(page: object) -> Page:
    """将对象转为 Playwright Page，非 Page 则抛出异常。"""
    if isinstance(page, Page):
        return page
    raise RuntimeError(
        "Render context is not a Playwright Page instance."
    )  # pragma: no cover


def register_render_context_provider(provider: RenderContextProvider) -> None:
    """注册渲染上下文提供器。"""
    _render_context_state["provider"] = provider


def _get_registered_render_context(
    **kwargs: Unpack[PageContextKwargs],
) -> AsyncContextManager[object]:
    """获取已注册的渲染上下文。"""
    provider = _render_context_state["provider"]
    if provider is None:
        raise RuntimeError(
            "No render context provider is registered. "
            "Use `nonebot_plugin_htmlrender.render` APIs or pass `session=` explicitly."
        )
    return provider(**kwargs)


def _get_session_browser(session: SupportsBrowserSession) -> Browser:
    """从会话中提取 Browser 实例。"""
    handle = session.handle
    if isinstance(handle, Browser):
        return handle
    raise RuntimeError("Session does not expose a Browser handle.")  # pragma: no cover


@asynccontextmanager
async def open_page_context(
    *,
    session: SupportsBrowserSession | None = None,
    **kwargs: Unpack[PageContextKwargs],
) -> AsyncIterator[Page]:
    """打开页面上下文，支持传入会话或使用已注册的提供器。"""
    if session is None:
        async with _get_registered_render_context(**kwargs) as context:
            yield _as_page(context)
        return

    browser = _get_session_browser(session)
    page = await browser.new_page(**kwargs)
    instrument_page(page, page_name="render_context")
    async with page:
        yield page
    detach_page(page)


def _is_local_or_private_target(url: str) -> bool:
    """判断 URL 是否指向本地或私有网络地址。"""
    parsed = urlparse(url)
    host = parsed.hostname
    if host is None:
        return False
    host_lower = host.lower()
    if host_lower == "localhost":
        return True
    if "." not in host_lower:
        # Docker compose service name or short host name.
        return True
    try:
        ip = ipaddress.ip_address(host_lower)
    except ValueError:
        return host_lower.endswith(".local")
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
    )


def _redact_url(value: str) -> str:
    """脱敏 URL，移除查询参数和认证信息。"""
    try:
        parsed = urlsplit(value)
    except Exception:
        return value

    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _setup_page_logging(page: Page) -> None:
    """为页面设置控制台和错误日志监听。"""
    page.on("console", lambda msg: logger.debug(f"[Browser Console]: {msg.text}"))
    page.on("pageerror", lambda exc: logger.warning(f"[Page Error]: {exc}"))
    page.on(
        "requestfailed",
        lambda req: logger.warning(
            "Playwright request failed: "
            f"url={_redact_url(req.url)}, method={req.method}, "
            f"resource_type={req.resource_type}, "
            f"error={req.failure or 'unknown'}"
        ),
    )
    page.on(
        "response",
        lambda resp: (
            logger.warning(
                "Playwright response error: "
                f"url={_redact_url(resp.url)}, status={resp.status}, "
                f"resource_type={resp.request.resource_type}"
            )
            if resp.status >= 400
            and resp.request.resource_type in {"image", "document"}
            else None
        ),
    )


def _iter_http_urls(value: object) -> list[str]:
    """递归提取对象中的所有 HTTP/HTTPS URL。"""
    urls: list[str] = []
    if isinstance(value, str):
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            urls.append(value)
        return urls
    if isinstance(value, dict):
        for nested in value.values():
            urls.extend(_iter_http_urls(nested))
        return urls
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            urls.extend(_iter_http_urls(nested))
        return urls
    return urls


def _origin(url: str) -> tuple[str, str, int | None] | None:
    """提取 URL 的 origin 三元组。"""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return (parsed.scheme, parsed.hostname or "", parsed.port)


def check_remote_pna_context(
    *,
    base_url: str,
    template_vars: dict[str, object],
    strict: bool,
) -> None:
    """检查远程渲染场景下的 PNA 安全性。"""
    resource_urls = [
        u for u in _iter_http_urls(template_vars) if _is_local_or_private_target(u)
    ]
    if not resource_urls:
        return

    parsed_base = urlparse(base_url)
    base_scheme = parsed_base.scheme.lower()
    base_origin = _origin(base_url)
    offending_urls = [
        u
        for u in resource_urls
        if base_scheme not in {"http", "https"} or _origin(u) != base_origin
    ]
    if not offending_urls:
        return

    sample = offending_urls[0]
    redacted_sample = _redact_url(sample)
    redacted_base = _redact_url(base_url)
    message = (
        "PNA precheck failed for remote Playwright rendering: detected local/private "
        f"resource URL {redacted_sample!r} under base_url {redacted_base!r}. "
        "This often gets blocked "
        "by Chromium as Private Network Access (PNA). Use a same-origin HTTP(S) "
        "`pages.base_url` (for example the resource origin) before rendering."
    )
    if strict:
        raise RuntimeError(message)
    logger.warning(message)


def _should_attach_filehost_header(url: str) -> bool:
    """判断请求是否应附加 filehost 认证头。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.path.startswith("/filehost/"):
        return False
    return _is_local_or_private_target(url)


async def install_filehost_request_route(
    page: Page,
    *,
    filehost_headers: dict[str, str],
) -> None:
    """为页面安装 filehost 请求路由拦截。"""
    if not filehost_headers:
        return

    async def _route_handler(route: Route) -> None:
        request = route.request
        if _should_attach_filehost_header(request.url):
            merged_headers = dict(request.headers)
            for key, value in filehost_headers.items():
                merged_headers.setdefault(key, value)
            await route.continue_(headers=merged_headers)
            return
        await route.continue_()

    await page.route("**/*", _route_handler)


__all__ = [
    "RenderContextProvider",
    "SupportsBrowserSession",
    "check_remote_pna_context",
    "install_filehost_request_route",
    "open_page_context",
    "register_render_context_provider",
]
