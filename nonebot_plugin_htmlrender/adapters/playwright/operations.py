from __future__ import annotations

from html import unescape
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urldefrag, urlsplit

from anyio import CancelScope
from nonebot.log import logger

from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.preparation.assets import (
    PreparedAssetIndex,
    resolve_document_reference,
)
from nonebot_plugin_htmlrender.preparation.materialize import (
    AssetMaterializationError,
    materialize_local_assets,
)
from nonebot_plugin_htmlrender.preparation.references import (
    css_resource_references,
    inspect_html_references,
    rewrite_css_references,
)
from nonebot_plugin_htmlrender.rendering.errors import ResourceResolutionError
from nonebot_plugin_htmlrender.resources import PackageResourceSource

from ._page import (
    _setup_page_logging,
    install_filehost_request_route,
    open_page_context,
)
from .models import (
    ContentConfig,
    JpegScreenshotOptions,
    RenderConfig,
    _page_context_kwargs,
)
from .prepared import (
    BrowserLoadPlan,
    build_browser_load_plan,
    install_browser_asset_routes,
)
from .telemetry import log_page_telemetry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nonebot_plugin_htmlrender.preparation import PreparedAsset, PreparedHtml
    from nonebot_plugin_htmlrender.resources.ports import AssetPublisher
    from nonebot_plugin_htmlrender.resources.service import ResourceService

    from .render import PlaywrightLease
    from .types import GotoKwargs, LocatorScreenshotKwargs, PageContextKwargs

EMPTY_PAGE_CONTEXT_KWARGS: PageContextKwargs = {}
EMPTY_GOTO_KWARGS: GotoKwargs = {}
EMPTY_LOCATOR_SCREENSHOT_KWARGS: LocatorScreenshotKwargs = {}
BUILTIN_TEMPLATES = PackageResourceSource(
    "nonebot_plugin_htmlrender",
    "templates",
)


def _enum_value(raw: object) -> str:
    """获取枚举值的字符串表示。"""
    return str(getattr(raw, "value", raw))


def _is_remote_lease(lease: PlaywrightLease) -> bool:
    return _enum_value(lease.mode) in {"remote_cdp", "remote_ws"}


def _document_url_for_render(
    render: RenderConfig,
) -> str | None:
    """Return only the explicit navigation URL; resource bases live elsewhere."""
    document_url = render.page.document_url
    if document_url in {None, "about:blank"}:
        return None
    return document_url


def _local_resource_policy(
    resources: ResourceService,
    *,
    remote_mode: bool,
) -> str:
    strategy = resources.strategy
    policy = (
        strategy.remote_local_policy if remote_mode else strategy.local_local_policy
    )
    return _enum_value(policy)


def _prepared_references(
    prepared: PreparedHtml,
    *,
    fallback_base_url: str | None = None,
) -> list[tuple[str, str | None]]:
    root_base = prepared.base_url or fallback_base_url
    snapshot = inspect_html_references(
        prepared.html,
        base_url=root_base,
    )
    document_base_url = (
        resolve_document_reference(root_base, snapshot.base_href)
        if snapshot.base_href is not None
        else root_base
    )
    references = [(reference, document_base_url) for reference in snapshot.references]
    for stylesheet in prepared.stylesheets:
        if stylesheet.embedded:
            continue
        references.extend(
            (reference, stylesheet.base_url or document_base_url)
            for reference in css_resource_references(stylesheet.css)
        )
    return references


def _assert_no_local_resources(
    prepared: PreparedHtml,
    *,
    document_url: str | None,
) -> None:
    if document_url is not None and urlsplit(document_url).scheme == "file":
        raise AssetMaterializationError(
            "Local file document URLs are not allowed under the error resource policy."
        )
    fallback_base = (
        document_url
        if prepared.base_url is None
        and document_url is not None
        and urlsplit(document_url).scheme in {"http", "https"}
        else None
    )
    index = PreparedAssetIndex(
        prepared.assets,
        base_url=prepared.base_url or fallback_base,
    )
    for reference, base_url in _prepared_references(
        prepared,
        fallback_base_url=fallback_base,
    ):
        base_url = base_url or fallback_base
        if index.match(reference, base_url=base_url) is not None:
            continue
        canonical = resolve_document_reference(base_url, reference)
        parsed = urlsplit(canonical)
        if parsed.scheme == "file" or (
            not parsed.scheme and not canonical.startswith("#")
        ):
            raise AssetMaterializationError(
                f"Local resource {reference!r} is not allowed under the error "
                "resource policy."
            )


def _asset_media_type(asset: PreparedAsset) -> str:
    return asset.media_type or mimetypes.guess_type(asset.source)[0] or ""


def _asset_suffix(asset: PreparedAsset) -> str | None:
    media_type = _asset_media_type(asset)
    if media_type == "text/css":
        return ".css"
    if media_type and (guessed := mimetypes.guess_extension(media_type, strict=False)):
        return guessed
    source_suffix = Path(urlsplit(asset.source).path).suffix.lower()
    return source_suffix or None


async def _publish_prepared_assets(
    prepared: PreparedHtml,
    *,
    publisher: AssetPublisher,
    lease_id: str,
) -> dict[str, str]:
    """Publish an asset graph bottom-up, rewriting CSS children to hosted URLs."""
    index = PreparedAssetIndex(prepared.assets, base_url=prepared.base_url)
    published: dict[int, str] = {}
    visiting: set[int] = set()

    async def publish(asset: PreparedAsset) -> str:
        asset_id = id(asset)
        if (url := published.get(asset_id)) is not None:
            return url
        if asset_id in visiting:
            raise AssetMaterializationError(
                f"Cyclic prepared stylesheet dependency at {asset.source!r}"
            )
        visiting.add(asset_id)
        payload = asset.data
        if _asset_media_type(asset) == "text/css":
            try:
                css = payload.decode("utf-8-sig")
            except UnicodeDecodeError:
                pass
            else:
                child_urls: dict[int, str] = {}
                for reference in css_resource_references(css):
                    child = index.match(reference, base_url=asset.source)
                    if child is not None:
                        child_urls[id(child)] = await publish(child)

                def rewrite_child(reference: str) -> str | None:
                    child = index.match(reference, base_url=asset.source)
                    if child is None:
                        normalized = unescape(reference).strip()
                        resolved = resolve_document_reference(asset.source, normalized)
                        if not resolved or resolved == normalized:
                            return None
                        _, fragment = urldefrag(normalized)
                        return f"{resolved}#{fragment}" if fragment else resolved
                    if (child_url := child_urls.get(id(child))) is None:
                        return None
                    _, fragment = urldefrag(unescape(reference).strip())
                    return f"{child_url}#{fragment}" if fragment else child_url

                payload = rewrite_css_references(css, rewrite_child).encode("utf-8")
        url = await publisher.publish(
            payload,
            lease_id=lease_id,
            suffix=_asset_suffix(asset),
        )
        published[asset_id] = url
        visiting.remove(asset_id)
        return url

    urls: dict[str, str] = {}
    for asset in prepared.assets:
        urls[asset.source] = await publish(asset)
    return urls


async def _execute_browser_load_plan(
    plan: BrowserLoadPlan,
    *,
    content: ContentConfig,
    render: RenderConfig,
    lease: PlaywrightLease,
    local_resource_policy: str,
    filehost_headers: Mapping[str, str],
    page_kwargs: PageContextKwargs,
    telemetry_op: str,
) -> bytes:
    """Execute a fully resolved load plan in one Playwright page."""
    async with open_page_context(
        lease=lease,
        **cast(
            "PageContextKwargs",
            {**_page_context_kwargs(render), **page_kwargs},
        ),
    ) as page:
        if local_resource_policy == RemoteLocalResourcePolicy.FILEHOST.value:
            await install_filehost_request_route(
                page,
                filehost_headers=dict(filehost_headers),
            )

        # Install the narrow route after the catch-all filehost route so it gets
        # first chance to fulfil immutable in-memory resources.
        await install_browser_asset_routes(page, plan)
        _setup_page_logging(page)
        if plan.document_url is not None:
            await page.goto(plan.document_url)
        await page.set_content(plan.html, wait_until=content.wait_until)
        await page.wait_for_timeout(content.additional_wait)
        await log_page_telemetry(page, op=telemetry_op)
        screenshot = render.screenshot
        await page.wait_for_timeout(screenshot.wait_before_screenshot)
        if isinstance(screenshot, JpegScreenshotOptions):
            return await page.screenshot(
                full_page=screenshot.full_page,
                type=screenshot.format,
                quality=screenshot.quality,
                timeout=screenshot.timeout,
            )
        return await page.screenshot(
            full_page=screenshot.full_page,
            type=screenshot.format,
            timeout=screenshot.timeout,
        )


async def render_prepared_html(
    prepared: PreparedHtml,
    *,
    content: ContentConfig,
    render: RenderConfig,
    lease: PlaywrightLease,
    resources: ResourceService,
    asset_publisher: AssetPublisher | None,
    page_kwargs: PageContextKwargs | None = None,
    resolve_mode: ResourceResolveMode | None = None,
    filehost_lease_id: str | None = None,
    telemetry_op: str = "playwright.html_render.render_html",
) -> bytes:
    """Apply local-resource policy and render a prepared document."""
    remote_mode = _is_remote_lease(lease)
    mode = resolve_mode or resources.strategy.resolve_mode
    policy = (
        RemoteLocalResourcePolicy.PASSTHROUGH.value
        if mode is ResourceResolveMode.OFF
        else _local_resource_policy(resources, remote_mode=remote_mode)
    )
    document_url = _document_url_for_render(render)
    fallback_base_url = (
        document_url
        if prepared.base_url is None
        and document_url is not None
        and urlsplit(document_url).scheme in {"http", "https"}
        else None
    )
    strict = mode is ResourceResolveMode.STRICT
    asset_urls: dict[str, str] | None = None
    owns_lease = False
    try:
        if policy == RemoteLocalResourcePolicy.MEMORY.value:
            prepared = await materialize_local_assets(
                prepared,
                resources=resources,
                strict=strict,
                fallback_base_url=fallback_base_url,
            )
        elif policy == RemoteLocalResourcePolicy.FILEHOST.value:
            prepared = await materialize_local_assets(
                prepared,
                resources=resources,
                strict=strict,
                fallback_base_url=fallback_base_url,
            )
            if prepared.assets:
                if asset_publisher is None:
                    raise ResourceResolutionError(
                        "The filehost resource policy requires an AssetPublisher."
                    )
                if filehost_lease_id is None:
                    filehost_lease_id = asset_publisher.create_lease()
                    owns_lease = True
                asset_urls = await _publish_prepared_assets(
                    prepared,
                    publisher=asset_publisher,
                    lease_id=filehost_lease_id,
                )
        elif policy == RemoteLocalResourcePolicy.ERROR.value:
            _assert_no_local_resources(prepared, document_url=document_url)
        elif policy not in {
            RemoteLocalResourcePolicy.PASSTHROUGH.value,
            LocalLocalResourcePolicy.FILE.value,
        }:
            raise RuntimeError(f"Unsupported local resource policy: {policy!r}")

        plan = build_browser_load_plan(
            prepared,
            document_url=document_url,
            asset_urls=asset_urls,
            allow_file_base_href=(
                policy
                in {
                    RemoteLocalResourcePolicy.PASSTHROUGH.value,
                    LocalLocalResourcePolicy.FILE.value,
                }
            ),
        )
        return await _execute_browser_load_plan(
            plan,
            content=content,
            render=render,
            lease=lease,
            local_resource_policy=policy,
            filehost_headers=(
                asset_publisher.request_headers()
                if policy == RemoteLocalResourcePolicy.FILEHOST.value
                and asset_publisher is not None
                else {}
            ),
            page_kwargs=page_kwargs or EMPTY_PAGE_CONTEXT_KWARGS,
            telemetry_op=telemetry_op,
        )
    finally:
        if owns_lease and filehost_lease_id is not None and asset_publisher is not None:
            with CancelScope(shield=True):
                await asset_publisher.release(filehost_lease_id)


async def capture_html_element(
    url: str,
    element: str,
    page_kwargs: PageContextKwargs | None = None,
    goto_kwargs: GotoKwargs | None = None,
    screenshot_kwargs: LocatorScreenshotKwargs | None = None,
    *,
    lease: PlaywrightLease,
) -> bytes:
    """捕获指定 URL 页面中的 HTML 元素截图。

    Args:
        url: 目标页面 URL。
        element: CSS 选择器，指定要捕获的元素。
        page_kwargs: 页面上下文配置。
        goto_kwargs: 页面导航配置。
        screenshot_kwargs: 元素截图配置。
        session: 浏览器会话。

    Returns:
        捕获的元素图片字节数据。
    """
    page_options = page_kwargs or EMPTY_PAGE_CONTEXT_KWARGS
    goto_options = goto_kwargs or EMPTY_GOTO_KWARGS
    screenshot_options = screenshot_kwargs or EMPTY_LOCATOR_SCREENSHOT_KWARGS

    async with open_page_context(lease=lease, **page_options) as page:
        page.on(
            "console",
            lambda msg: logger.opt(colors=True).debug(
                f"<cyan>[Browser Console]</cyan> {msg.text}"
            ),
        )
        await page.goto(url, **goto_options)
        await log_page_telemetry(page, op="playwright.html_render.capture_html_element")
        return await page.locator(element).screenshot(**screenshot_options)


__all__ = [
    "capture_html_element",
    "render_prepared_html",
]
