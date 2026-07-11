"""Adapt backend-neutral prepared documents for browser execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from html import escape, unescape
from html.parser import HTMLParser
import mimetypes
import re
from typing import TYPE_CHECKING
from urllib.parse import urldefrag, urlsplit

from nonebot_plugin_htmlrender.preparation.assets import (
    PreparedAssetIndex,
    resolve_document_reference,
)
from nonebot_plugin_htmlrender.preparation.references import (
    inspect_html_references,
    rewrite_css_references,
    rewrite_html_references,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from playwright.async_api import Page, Route

    from nonebot_plugin_htmlrender.preparation import PreparedAsset, PreparedHtml

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

    ``document_url`` controls navigation. It is intentionally independent from
    ``PreparedHtml.base_url``, which only controls relative resource resolution.
    """

    html: str
    document_url: str | None = None
    base_href: str | None = None
    asset_routes: tuple[BrowserAssetRoute, ...] = ()


def _asset_media_type(asset: PreparedAsset) -> str:
    media_type = asset.media_type or mimetypes.guess_type(asset.source)[0]
    media_type = media_type or "application/octet-stream"
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


class _DocumentStructureParser(HTMLParser):
    def __init__(self, markup: str) -> None:
        super().__init__(convert_charrefs=False)
        self.head_open_end: int | None = None
        self.doctype_end: int | None = None
        self.document_base_tag: tuple[int, int, str] | None = None
        self._line_offsets = [0]
        self._line_offsets.extend(
            index + 1 for index, char in enumerate(markup) if char == "\n"
        )

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_offsets[line - 1] + column

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._record_document_base(tag, attrs)
        if tag.lower() == "head" and self.head_open_end is None:
            raw = self.get_starttag_text()
            if raw is not None:
                self.head_open_end = self._offset() + len(raw)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._record_document_base(tag, attrs)

    def _record_document_base(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if (
            self.document_base_tag is not None
            or tag.lower() != "base"
            or not any(name.lower() == "href" and bool(value) for name, value in attrs)
        ):
            return
        raw = self.get_starttag_text()
        if raw is None:
            return
        start = self._offset()
        self.document_base_tag = (start, start + len(raw), raw)

    def handle_decl(self, decl: str) -> None:
        if self.doctype_end is None and decl.lower().startswith("doctype"):
            self.doctype_end = self._offset() + len(decl) + 3


def _document_structure(markup: str) -> _DocumentStructureParser:
    parser = _DocumentStructureParser(markup)
    parser.feed(markup)
    parser.close()
    return parser


def _inject_head_content(markup: str, content: str) -> str:
    if not content:
        return markup
    structure = _document_structure(markup)
    if structure.head_open_end is not None:
        insertion = structure.head_open_end
        return f"{markup[:insertion]}{content}{markup[insertion:]}"
    if structure.doctype_end is None:
        return f"<head>{content}</head>{markup}"
    insertion = structure.doctype_end
    return f"{markup[:insertion]}<head>{content}</head>{markup[insertion:]}"


def _replace_tag_attribute_value(raw: str, name: str, value: str) -> str:
    """Replace one real tag attribute value without rebuilding the tag."""
    cursor = 1
    length = len(raw)
    while cursor < length and not raw[cursor].isspace() and raw[cursor] not in ">/":
        cursor += 1

    replacements: list[tuple[int, int, str]] = []
    while cursor < length:
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length or raw[cursor] in ">/":
            break
        attribute_start = cursor
        while (
            cursor < length and not raw[cursor].isspace() and raw[cursor] not in "=/>"
        ):
            cursor += 1
        attribute_name = raw[attribute_start:cursor].lower()
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length or raw[cursor] != "=":
            continue
        cursor += 1
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length:
            break
        if raw[cursor] in {'"', "'"}:
            quote = raw[cursor]
            value_start = cursor + 1
            cursor = value_start
            while cursor < length and raw[cursor] != quote:
                cursor += 1
            value_end = cursor
            cursor += cursor < length
        else:
            value_start = cursor
            while cursor < length and not raw[cursor].isspace() and raw[cursor] != ">":
                cursor += 1
            value_end = cursor
        if attribute_name == name:
            replacements.append((value_start, value_end, escape(value, quote=True)))

    for start, end, replacement in reversed(replacements):
        raw = f"{raw[:start]}{replacement}{raw[end:]}"
    return raw


def _canonicalize_document_base(markup: str, base_href: str) -> str:
    """Canonicalize the first real document base while preserving source order."""
    structure = _document_structure(markup)
    if structure.document_base_tag is None:
        return markup
    start, end, raw = structure.document_base_tag
    rewritten = _replace_tag_attribute_value(raw, "href", base_href)
    if rewritten == raw:
        return markup
    return f"{markup[:start]}{rewritten}{markup[end:]}"


def _inject_stylesheets(
    markup: str,
    prepared: PreparedHtml,
    *,
    index: PreparedAssetIndex,
    route_urls: dict[int, str],
    document_base_url: str | None,
) -> str:
    blocks: list[str] = []
    for stylesheet in prepared.stylesheets:
        # Embedded styles already occur in the original document. Re-injecting
        # them would change cascade order and drop attributes such as media/type.
        if stylesheet.embedded:
            continue
        css = _replace_css_asset_references(
            stylesheet.css,
            base_url=stylesheet.base_url or document_base_url,
            index=index,
            route_urls=route_urls,
        )
        media = (
            f' media="{escape(stylesheet.media, quote=True)}"'
            if stylesheet.media
            else ""
        )
        blocks.append(f"<style{media}>{css}</style>")
    return _inject_head_content(markup, "".join(blocks))


def _inject_resource_base(
    markup: str,
    base_url: str | None,
    *,
    has_document_base: bool,
) -> str:
    if not base_url or base_url == "about:blank" or has_document_base:
        return markup
    return _inject_head_content(
        markup,
        f'<base href="{escape(base_url, quote=True)}">',
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
    resource_root = prepared.base_url
    if (
        resource_root is None
        and document_url is not None
        and urlsplit(document_url).scheme in {"http", "https"}
    ):
        resource_root = document_url
    snapshot = inspect_html_references(prepared.html, base_url=resource_root)
    document_base_url = (
        resolve_document_reference(resource_root, snapshot.base_href)
        if snapshot.base_href is not None
        else resource_root
    )
    index, route_urls, asset_routes = _build_asset_transport(
        prepared,
        asset_urls=asset_urls,
        document_base_url=document_base_url,
    )

    # Rewrite the original document in place so embedded <style> elements retain
    # their attributes and exact position. External stylesheets are injected once.
    document = _replace_html_asset_references(
        prepared.html,
        base_url=document_base_url,
        index=index,
        route_urls=route_urls,
    )
    document = _inject_stylesheets(
        document,
        prepared,
        index=index,
        route_urls=route_urls,
        document_base_url=document_base_url,
    )
    base_href = (
        document_base_url
        if document_base_url
        and (
            snapshot.base_href is not None
            or document_base_url.startswith(("http://", "https://"))
            or (allow_file_base_href and document_base_url.startswith("file://"))
        )
        else None
    )
    if snapshot.base_href is not None and base_href is not None:
        document = _canonicalize_document_base(document, base_href)
    document = _inject_resource_base(
        document,
        base_href,
        has_document_base=snapshot.base_href is not None,
    )
    return BrowserLoadPlan(
        html=document,
        document_url=document_url,
        base_href=base_href,
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
