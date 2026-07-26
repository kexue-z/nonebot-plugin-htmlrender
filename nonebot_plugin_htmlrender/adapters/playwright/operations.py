from __future__ import annotations

from html import unescape
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urldefrag, urlsplit, urlunsplit

from anyio import CancelScope

from nonebot_plugin_htmlrender.preparation.assets import (
    PreparedAssetIndex,
    resolve_document_reference,
)
from nonebot_plugin_htmlrender.preparation.materialize import (
    AssetMaterializationError,
    materialize_local_assets,
)
from nonebot_plugin_htmlrender.preparation.media import guess_asset_media_type
from nonebot_plugin_htmlrender.preparation.references import (
    css_resource_references,
    rewrite_css_references,
)
from nonebot_plugin_htmlrender.rendering.errors import ResourceResolutionError
from nonebot_plugin_htmlrender.resources import PackageResourceSource
from nonebot_plugin_htmlrender.resources.config import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)

from ._page import (
    PageContext,
    _setup_page_logging,
    install_filehost_request_route,
)
from .models import (
    ContentConfig,
    JpegScreenshotOptions,
    RenderConfig,
)
from .prepared import (
    BrowserLoadPlan,
    build_browser_load_plan,
    install_browser_asset_routes,
)
from .render import PlaywrightMode
from .telemetry import log_page_telemetry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nonebot_plugin_htmlrender.preparation import PreparedAsset, PreparedHtml
    from nonebot_plugin_htmlrender.resources.ports import (
        AssetPublisher,
        ProviderResources,
    )

    from .render import PlaywrightLease

BUILTIN_TEMPLATES = PackageResourceSource(
    "nonebot_plugin_htmlrender",
    "templates",
)


def _is_remote_lease(lease: PlaywrightLease) -> bool:
    return lease.mode in (PlaywrightMode.REMOTE_CDP, PlaywrightMode.REMOTE_WS)


def _document_url_for_render(
    render: RenderConfig,
) -> str | None:
    """Return only the explicit navigation URL; resource bases live elsewhere."""
    document_url = render.page.document_url
    if document_url in {None, "about:blank"}:
        return None
    return document_url


def _local_resource_policy(
    resources: ProviderResources,
    *,
    remote_mode: bool,
) -> LocalLocalResourcePolicy | RemoteLocalResourcePolicy:
    strategy = resources.strategy
    return strategy.remote_local_policy if remote_mode else strategy.local_local_policy


def _prepared_references(
    prepared: PreparedHtml,
    *,
    fallback_base_url: str | None = None,
) -> list[tuple[str, str | None]]:
    document_base_url = prepared.document_base.resolve(
        fallback_base_url=fallback_base_url
    )
    references = [
        (reference, document_base_url) for reference in prepared.structure.references
    ]
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
        if prepared.document_base.preparation_base_url is None
        and document_url is not None
        and urlsplit(document_url).scheme in {"http", "https"}
        else None
    )
    index = PreparedAssetIndex(
        prepared.assets,
        base_url=prepared.document_base.preparation_base_url or fallback_base,
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
    return guess_asset_media_type(asset) or ""


def _asset_suffix(asset: PreparedAsset) -> str | None:
    media_type = _asset_media_type(asset)
    if media_type == "text/css":
        return ".css"
    if media_type and (guessed := mimetypes.guess_extension(media_type, strict=False)):
        return guessed
    source_suffix = Path(urlsplit(asset.source).path).suffix.lower()
    return source_suffix or None


def _normalize_authorized_url(url: str) -> str:
    """Canonical identity for matching a published URL against a request.

    Only scheme/host case, the default port and the fragment are normalized;
    path and query stay part of the identity so a different query or a
    redirect target does not inherit another resource's authorization.
    """
    split = urlsplit(url)
    scheme = split.scheme.lower()
    host = (split.hostname or "").lower()
    default_port = {"http": 80, "https": 443}.get(scheme)
    port = split.port
    netloc = host if port is None or port == default_port else f"{host}:{port}"
    return urlunsplit((scheme, netloc, split.path, split.query, ""))


async def _publish_prepared_assets(
    prepared: PreparedHtml,
    *,
    publisher: AssetPublisher,
    lease_id: str,
) -> tuple[dict[str, str], dict[str, Mapping[str, str]]]:
    """Publish an asset graph bottom-up, rewriting CSS children to hosted URLs.

    Returns the ``source -> hosted URL`` transport map and a
    ``normalized URL -> request headers`` authorization map covering every
    publication (including CSS sub-resources).
    """
    index = PreparedAssetIndex(
        prepared.assets,
        base_url=prepared.document_base.preparation_base_url,
    )
    published: dict[int, str] = {}
    visiting: set[int] = set()
    authorization: dict[str, Mapping[str, str]] = {}

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
        result = await publisher.publish(
            payload,
            lease_id=lease_id,
            suffix=_asset_suffix(asset),
        )
        authorization[_normalize_authorized_url(result.url)] = result.request_headers
        published[asset_id] = result.url
        visiting.remove(asset_id)
        return result.url

    urls: dict[str, str] = {}
    for asset in prepared.assets:
        urls[asset.source] = await publish(asset)
    return urls, authorization


async def _execute_browser_load_plan(
    plan: BrowserLoadPlan,
    *,
    content: ContentConfig,
    render: RenderConfig,
    lease: PlaywrightLease,
    local_resource_policy: LocalLocalResourcePolicy | RemoteLocalResourcePolicy,
    filehost_authorization: Mapping[str, Mapping[str, str]],
    telemetry_op: str,
) -> bytes:
    """Execute a fully resolved load plan in one Playwright page."""
    async with PageContext(lease).open(
        viewport={
            "width": render.page.viewport.width,
            "height": render.page.viewport.height,
        },
        device_scale_factor=render.screenshot.device_scale_factor,
        user_agent=render.page.user_agent,
        extra_http_headers=render.page.extra_http_headers,
    ) as page:
        if local_resource_policy == RemoteLocalResourcePolicy.FILEHOST:
            await install_filehost_request_route(
                page,
                authorization=filehost_authorization,
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
    resources: ProviderResources,
    asset_publisher: AssetPublisher | None,
    resolve_mode: ResourceResolveMode | None = None,
    filehost_lease_id: str | None = None,
    telemetry_op: str = "playwright.html_render.render_html",
) -> bytes:
    """Apply local-resource policy and render a prepared document."""
    remote_mode = _is_remote_lease(lease)
    mode = resolve_mode or resources.strategy.resolve_mode
    policy = (
        RemoteLocalResourcePolicy.PASSTHROUGH
        if mode is ResourceResolveMode.OFF
        else _local_resource_policy(resources, remote_mode=remote_mode)
    )
    document_url = _document_url_for_render(render)
    fallback_base_url = (
        document_url
        if prepared.document_base.preparation_base_url is None
        and document_url is not None
        and urlsplit(document_url).scheme in {"http", "https"}
        else None
    )
    strict = mode is ResourceResolveMode.STRICT
    asset_urls: dict[str, str] | None = None
    filehost_authorization: dict[str, Mapping[str, str]] = {}
    owns_lease = False
    try:
        if policy is RemoteLocalResourcePolicy.MEMORY:
            prepared = await materialize_local_assets(
                prepared,
                resources=resources,
                strict=strict,
                fallback_base_url=fallback_base_url,
            )
        elif policy == RemoteLocalResourcePolicy.FILEHOST:
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
                asset_urls, filehost_authorization = await _publish_prepared_assets(
                    prepared,
                    publisher=asset_publisher,
                    lease_id=filehost_lease_id,
                )
        elif policy is RemoteLocalResourcePolicy.ERROR:
            _assert_no_local_resources(prepared, document_url=document_url)
        elif policy not in (
            RemoteLocalResourcePolicy.PASSTHROUGH,
            LocalLocalResourcePolicy.FILE,
        ):
            raise RuntimeError(f"Unsupported local resource policy: {policy!r}")

        plan = build_browser_load_plan(
            prepared,
            document_url=document_url,
            asset_urls=asset_urls,
            allow_file_base_href=(
                policy
                in (
                    RemoteLocalResourcePolicy.PASSTHROUGH,
                    LocalLocalResourcePolicy.FILE,
                )
            ),
        )
        return await _execute_browser_load_plan(
            plan,
            content=content,
            render=render,
            lease=lease,
            local_resource_policy=policy,
            filehost_authorization=filehost_authorization,
            telemetry_op=telemetry_op,
        )
    finally:
        if owns_lease and filehost_lease_id is not None and asset_publisher is not None:
            with CancelScope(shield=True):
                await asset_publisher.release(filehost_lease_id)


__all__ = ["render_prepared_html"]
