"""Build one policy-bound HTMLKit document from the neutral prepared IR."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, final
from urllib.parse import urldefrag, urlsplit

from nonebot.log import logger

from nonebot_plugin_htmlrender.preparation.assets import (
    PreparedAssetIndex,
    resolve_document_reference,
)
from nonebot_plugin_htmlrender.preparation.document import resolve_document
from nonebot_plugin_htmlrender.preparation.materialize import (
    materialize_local_assets,
)
from nonebot_plugin_htmlrender.preparation.references import (
    rewrite_css_references,
)
from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode
from nonebot_plugin_htmlrender.resources.errors import ResourceResolutionError
from nonebot_plugin_htmlrender.resources.models import RemoteResourceRef

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        PreparedStylesheet,
    )
    from nonebot_plugin_htmlrender.resources.ports import ProviderResources


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
                f"Could not fetch HTMLKit resource {url!r}.",
                source=error,
            )
        )
        if self._strict:
            self._errors.append(translated)
        else:
            logger.warning(
                "Could not fetch an HTMLKit resource (non-strict): {}",
                type(error).__name__,
            )

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

    document_base = materialized.document_base.resolve()

    def resolved_css(stylesheet: PreparedStylesheet) -> str:
        return rewrite_css_references(
            stylesheet.css,
            partial(
                _resolve_stylesheet_reference,
                base_url=stylesheet.base_url or document_base,
            ),
        )

    resolved = resolve_document(materialized, stylesheet_css=resolved_css)
    bridge = HtmlkitResourceBridge(
        materialized,
        document_base=document_base,
        resources=resources,
        strict=resolve_mode is ResourceResolveMode.STRICT,
    )
    return HtmlkitDocument(
        html=resolved.markup,
        base_url=materialized.document_base.preparation_base_url or "",
        resources=bridge,
    )


__all__ = [
    "HtmlkitDocument",
    "HtmlkitResourceBridge",
    "build_htmlkit_document",
]
