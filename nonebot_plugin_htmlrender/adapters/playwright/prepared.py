"""Adapt backend-neutral prepared documents for browser execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from html import unescape
import re
from typing import TYPE_CHECKING
from urllib.parse import urldefrag, urlsplit

from nonebot_plugin_htmlrender.preparation.assets import (
    PreparedAssetIndex,
    resolve_document_reference,
)
from nonebot_plugin_htmlrender.preparation.document import resolve_document
from nonebot_plugin_htmlrender.preparation.media import guess_asset_media_type
from nonebot_plugin_htmlrender.preparation.references import (
    rewrite_css_references,
    rewrite_html_references,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from playwright.async_api import Page, Route

    from nonebot_plugin_htmlrender.preparation import PreparedAsset, PreparedHtml
    from nonebot_plugin_htmlrender.preparation.models import PreparedStylesheet

_MEMORY_ASSET_ORIGIN = "https://htmlrender.invalid"
_MEMORY_ASSET_PREFIX = f"{_MEMORY_ASSET_ORIGIN}/.htmlrender/assets/"
_MEDIA_TYPE_RE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")


@dataclass(frozen=True, slots=True)
class BrowserAssetRoute:
    """One immutable prepared asset exposed to the browser through routing."""

    url: str
    asset: PreparedAsset


@dataclass(frozen=True, slots=True)
class BrowserLoadPlan:
    """A browser document and the resources required to load it.

    ``document_url`` controls navigation. It is intentionally independent
    from the prepared document base, which only controls relative resource
    resolution.
    """

    html: str
    document_url: str | None = None
    base_href: str | None = None
    asset_routes: tuple[BrowserAssetRoute, ...] = ()


def _asset_media_type(asset: PreparedAsset) -> str:
    media_type = guess_asset_media_type(asset) or "application/octet-stream"
    if _MEDIA_TYPE_RE.fullmatch(media_type) is None:
        raise ValueError(f"Invalid PreparedAsset media type: {media_type!r}")
    return media_type


def _asset_route_url(asset: PreparedAsset) -> str:
    return f"{_MEMORY_ASSET_PREFIX}{sha256(asset.data).hexdigest()}"


def _replacement_for(
    reference: str,
    *,
    base_url: str | None,
    index: PreparedAssetIndex,
    route_urls: dict[int, str],
) -> str | None:
    normalized = unescape(reference).strip()
    asset = index.match(normalized, base_url=base_url)
    if asset is None:
        return None
    _, fragment = urldefrag(normalized)
    replacement = route_urls[id(asset)]
    return f"{replacement}#{fragment}" if fragment else replacement


def _resolved_reference(base_url: str | None, reference: str) -> str | None:
    normalized = unescape(reference).strip()
    resolved = resolve_document_reference(base_url, normalized)
    if not resolved or resolved == normalized:
        return None
    _, fragment = urldefrag(normalized)
    return f"{resolved}#{fragment}" if fragment else resolved


def _reference_rewriter(
    *,
    base_url: str | None,
    index: PreparedAssetIndex,
    route_urls: dict[int, str],
    resolve_unmatched: bool = False,
) -> Callable[[str], str | None]:
    def rewrite(reference: str) -> str | None:
        replacement = _replacement_for(
            reference,
            base_url=base_url,
            index=index,
            route_urls=route_urls,
        )
        if replacement is not None or not resolve_unmatched:
            return replacement
        return _resolved_reference(base_url, reference)

    return rewrite


def _replace_html_asset_references(
    value: str,
    *,
    base_url: str | None,
    index: PreparedAssetIndex,
    route_urls: dict[int, str],
) -> str:
    if not route_urls:
        return value
    return rewrite_html_references(
        value,
        _reference_rewriter(
            base_url=base_url,
            index=index,
            route_urls=route_urls,
        ),
    )


def _replace_css_asset_references(
    value: str,
    *,
    base_url: str | None,
    index: PreparedAssetIndex,
    route_urls: dict[int, str],
) -> str:
    return rewrite_css_references(
        value,
        _reference_rewriter(
            base_url=base_url,
            index=index,
            route_urls=route_urls,
            resolve_unmatched=True,
        ),
    )


def _build_asset_transport(
    prepared: PreparedHtml,
    *,
    asset_urls: Mapping[str, str] | None,
    document_base_url: str | None,
) -> tuple[PreparedAssetIndex, dict[int, str], tuple[BrowserAssetRoute, ...]]:
    """Resolve an asset graph bottom-up so routed CSS has absolute child URLs."""
    index = PreparedAssetIndex(prepared.assets, base_url=document_base_url)
    route_by_url: dict[str, BrowserAssetRoute] = {}
    route_urls: dict[int, str] = {}
    visiting: set[int] = set()

    for asset in prepared.assets:
        _asset_media_type(asset)
        if asset_urls is not None and (url := asset_urls.get(asset.source)) is not None:
            route_urls[id(asset)] = url

    def resolve_asset(asset: PreparedAsset) -> str:
        asset_id = id(asset)
        if (existing_url := route_urls.get(asset_id)) is not None:
            return existing_url
        if asset_id in visiting:
            raise ValueError(
                f"Cyclic prepared stylesheet dependency at {asset.source!r}"
            )
        visiting.add(asset_id)
        transported = asset
        if _asset_media_type(asset) == "text/css":
            try:
                css = asset.data.decode("utf-8-sig")
            except UnicodeDecodeError:
                pass
            else:

                def rewrite_child(reference: str) -> str | None:
                    child = index.match(reference, base_url=asset.source)
                    if child is None:
                        return _resolved_reference(asset.source, reference)
                    _, fragment = urldefrag(unescape(reference).strip())
                    child_url = resolve_asset(child)
                    return f"{child_url}#{fragment}" if fragment else child_url

                rewritten = rewrite_css_references(css, rewrite_child)
                if rewritten != css:
                    transported = replace(asset, data=rewritten.encode("utf-8"))
        url = _asset_route_url(transported)
        route_urls[asset_id] = url
        route = BrowserAssetRoute(url=url, asset=transported)
        existing_route = route_by_url.get(url)
        if existing_route is not None and _asset_media_type(
            existing_route.asset
        ) != _asset_media_type(transported):
            raise ValueError(
                "Prepared assets with identical content have conflicting media "
                f"types: {_asset_media_type(existing_route.asset)!r} and "
                f"{_asset_media_type(transported)!r}"
            )
        route_by_url.setdefault(url, route)
        visiting.remove(asset_id)
        return url

    for asset in prepared.assets:
        resolve_asset(asset)
    return index, route_urls, tuple(route_by_url.values())


def build_browser_load_plan(
    prepared: PreparedHtml,
    *,
    document_url: str | None = None,
    asset_urls: Mapping[str, str] | None = None,
    allow_file_base_href: bool = False,
) -> BrowserLoadPlan:
    """Translate a prepared document into a route-backed browser load plan."""
    fallback = (
        document_url
        if document_url is not None
        and urlsplit(document_url).scheme in {"http", "https"}
        else None
    )
    document_base_url = prepared.document_base.resolve(fallback_base_url=fallback)
    index, route_urls, asset_routes = _build_asset_transport(
        prepared,
        asset_urls=asset_urls,
        document_base_url=document_base_url,
    )

    def routed_css(stylesheet: PreparedStylesheet) -> str:
        return _replace_css_asset_references(
            stylesheet.css,
            base_url=stylesheet.base_url or document_base_url,
            index=index,
            route_urls=route_urls,
        )

    # The shared materializer canonicalizes/injects <base> and injects the
    # external stylesheets by snapshot-offset splicing; embedded <style>
    # elements keep their attributes and exact position.
    resolved = resolve_document(
        prepared,
        fallback_base_url=fallback,
        allow_file_base_href=allow_file_base_href,
        inject_base=True,
        stylesheet_css=routed_css,
    )
    document = _replace_html_asset_references(
        resolved.markup,
        base_url=document_base_url,
        index=index,
        route_urls=route_urls,
    )
    return BrowserLoadPlan(
        html=document,
        document_url=document_url,
        base_href=resolved.base_href,
        asset_routes=asset_routes,
    )


async def install_browser_asset_routes(page: Page, plan: BrowserLoadPlan) -> None:
    """Fulfil synthetic prepared-asset requests through the Playwright channel."""
    if not plan.asset_routes:
        return
    routes = {route.url: route.asset for route in plan.asset_routes}

    async def handle(route: Route) -> None:
        request_url, _ = urldefrag(route.request.url)
        asset = routes.get(request_url)
        if asset is None:
            await route.abort()
            return
        await route.fulfill(
            status=200,
            body=asset.data,
            content_type=_asset_media_type(asset),
            headers={
                "access-control-allow-origin": "*",
                "cache-control": "public, max-age=31536000, immutable",
            },
        )

    await page.route(f"{_MEMORY_ASSET_PREFIX}**", handle)


def materialize_prepared_html(prepared: PreparedHtml) -> str:
    """Compatibility helper returning the document portion of a browser plan."""
    return build_browser_load_plan(prepared).html


__all__ = [
    "BrowserAssetRoute",
    "BrowserLoadPlan",
    "build_browser_load_plan",
    "install_browser_asset_routes",
    "materialize_prepared_html",
]
