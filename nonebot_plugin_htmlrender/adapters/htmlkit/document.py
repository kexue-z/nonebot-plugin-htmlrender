"""Build one policy-bound HTMLKit document from the neutral prepared IR."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from html import escape
from html.parser import HTMLParser
from typing import TYPE_CHECKING, final
from urllib.parse import urldefrag, urlsplit

from nonebot.log import logger

from nonebot_plugin_htmlrender.preparation.assets import (
    PreparedAssetIndex,
    resolve_document_reference,
)
from nonebot_plugin_htmlrender.preparation.materialize import (
    materialize_local_assets,
)
from nonebot_plugin_htmlrender.preparation.references import (
    inspect_html_references,
    rewrite_css_references,
)
from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode
from nonebot_plugin_htmlrender.resources.errors import ResourceResolutionError
from nonebot_plugin_htmlrender.resources.models import RemoteResourceRef

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml
    from nonebot_plugin_htmlrender.resources.ports import ProviderResources


class _HeadParser(HTMLParser):
    def __init__(self, markup: str) -> None:
        super().__init__(convert_charrefs=False)
        self.head_open_end: int | None = None
        self.doctype_end: int | None = None
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
        del attrs
        if tag.lower() != "head" or self.head_open_end is not None:
            return
        raw = self.get_starttag_text()
        if raw is not None:
            self.head_open_end = self._offset() + len(raw)

    def handle_decl(self, decl: str) -> None:
        if self.doctype_end is None and decl.lower().startswith("doctype"):
            self.doctype_end = self._offset() + len(decl) + 3


def _inject_head_content(markup: str, content: str) -> str:
    if not content:
        return markup
    parser = _HeadParser(markup)
    parser.feed(markup)
    parser.close()
    if parser.head_open_end is not None:
        insertion = parser.head_open_end
        return f"{markup[:insertion]}{content}{markup[insertion:]}"
    if parser.doctype_end is None:
        return f"<head>{content}</head>{markup}"
    insertion = parser.doctype_end
    return f"{markup[:insertion]}<head>{content}</head>{markup[insertion:]}"


def _external_stylesheets(prepared: PreparedHtml, document_base: str | None) -> str:
    blocks: list[str] = []
    for stylesheet in prepared.stylesheets:
        if stylesheet.embedded:
            continue
        base_url = stylesheet.base_url or document_base

        css = rewrite_css_references(
            stylesheet.css,
            partial(_resolve_stylesheet_reference, base_url=base_url),
        )
        media = (
            f' media="{escape(stylesheet.media, quote=True)}"'
            if stylesheet.media
            else ""
        )
        blocks.append(f"<style{media}>{css}</style>")
    return "".join(blocks)


def _resolve_stylesheet_reference(
    reference: str,
    *,
    base_url: str | None,
) -> str | None:
    resolved = resolve_document_reference(base_url, reference)
    return resolved if resolved != reference else None


@final
class HtmlkitResourceBridge:
    """Serve HTMLKit callbacks from prepared assets and the shared reader."""

    def __init__(
        self,
        prepared: PreparedHtml,
        *,
        document_base: str | None,
        resources: ProviderResources,
        strict: bool,
    ) -> None:
        self._assets = PreparedAssetIndex(
            prepared.assets,
            base_url=document_base,
        )
        self._document_base = document_base
        self._resources = resources
        self._strict = strict
        self._errors: list[ResourceResolutionError] = []

    def _record(self, url: str, error: BaseException) -> None:
        translated = (
            error
            if isinstance(error, ResourceResolutionError)
            else ResourceResolutionError(
                f"Could not fetch HTMLKit resource {url!r}: {error}"
            )
        )
        if self._strict:
            self._errors.append(translated)
        else:
            logger.warning("Could not fetch HTMLKit resource {!r}: {}", url, error)

    async def _bytes(self, url: str) -> bytes | None:
        asset = self._assets.match(url, base_url=self._document_base)
        if asset is not None:
            return asset.data

        normalized, _ = urldefrag(url.strip())
        scheme = urlsplit(normalized).scheme.lower()
        if scheme == "data":
            # HTMLKit's native decoder handles data URLs without a Python copy.
            return None
        if scheme in {"http", "https"}:
            try:
                return await self._resources.read_bytes(RemoteResourceRef(normalized))
            except Exception as error:
                self._record(normalized, error)
                return None
        if scheme == "file" and self._strict:
            self._record(
                normalized,
                ResourceResolutionError(
                    "HTMLKit requested a local resource that was not materialized."
                ),
            )
        return None

    async def fetch_image(self, url: str) -> bytes | None:
        return await self._bytes(url)

    async def fetch_stylesheet(self, url: str) -> str | None:
        data = await self._bytes(url)
        if data is None:
            return None
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            self._record(url, error)
            return None

    def raise_callback_error(self) -> None:
        if self._errors:
            raise self._errors[0]


@dataclass(frozen=True, slots=True)
class HtmlkitDocument:
    html: str
    base_url: str
    resources: HtmlkitResourceBridge


async def build_htmlkit_document(
    prepared: PreparedHtml,
    *,
    resources: ProviderResources,
    resolve_mode: ResourceResolveMode,
) -> HtmlkitDocument:
    """Apply local policy, preserve stylesheet bases, and bind fetch callbacks."""
    materialized = prepared
    if resolve_mode is not ResourceResolveMode.OFF:
        materialized = await materialize_local_assets(
            prepared,
            resources=resources,
            strict=resolve_mode is ResourceResolveMode.STRICT,
        )

    inspected = inspect_html_references(
        materialized.html,
        base_url=materialized.base_url,
    )
    document_base = (
        resolve_document_reference(materialized.base_url, inspected.base_href)
        if inspected.base_href
        else materialized.base_url
    )
    stylesheets = _external_stylesheets(materialized, document_base)
    bridge = HtmlkitResourceBridge(
        materialized,
        document_base=document_base,
        resources=resources,
        strict=resolve_mode is ResourceResolveMode.STRICT,
    )
    return HtmlkitDocument(
        html=_inject_head_content(materialized.html, stylesheets),
        base_url=materialized.base_url or "",
        resources=bridge,
    )


__all__ = [
    "HtmlkitDocument",
    "HtmlkitResourceBridge",
    "build_htmlkit_document",
]
