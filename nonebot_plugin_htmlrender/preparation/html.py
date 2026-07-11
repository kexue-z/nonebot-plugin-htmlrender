"""Prepare arbitrary HTML while preserving browser and native execution forms."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from .models import (
    PreparedAsset,
    PreparedHtml,
    PreparedStylesheet,
    RenderRequirement,
)
from .references import css_resource_references, inspect_html_references

if TYPE_CHECKING:
    from collections.abc import Iterable


def _resource_requirement(
    value: str,
    *,
    base_url: str | None,
) -> RenderRequirement | None:
    stripped = value.strip()
    if not stripped or stripped.startswith(("data:", "memory:", "#")):
        return None
    resolved = urljoin(base_url, stripped) if base_url else stripped
    parsed = urlsplit(resolved)
    if parsed.scheme in {"http", "https"}:
        return RenderRequirement.NETWORK
    if parsed.scheme == "file" or not parsed.scheme:
        return RenderRequirement.LOCAL_RESOURCE
    return None


def _normalize_stylesheet(
    stylesheet: str | PreparedStylesheet,
    *,
    base_url: str | None,
) -> PreparedStylesheet:
    if isinstance(stylesheet, PreparedStylesheet):
        return stylesheet
    return PreparedStylesheet(css=stylesheet, base_url=base_url)


def prepare_html(
    html: str,
    *,
    base_url: str | None = None,
    stylesheets: Iterable[str | PreparedStylesheet] = (),
    assets: Iterable[PreparedAsset] = (),
) -> PreparedHtml:
    """Build a canonical payload without performing backend-specific transport."""

    inspected = inspect_html_references(html, base_url=base_url)
    document_base = (
        urljoin(base_url, inspected.base_href)
        if base_url and inspected.base_href
        else inspected.base_href or base_url
    )
    external_stylesheets = tuple(
        _normalize_stylesheet(stylesheet, base_url=base_url)
        for stylesheet in stylesheets
    )
    embedded_stylesheets = tuple(
        PreparedStylesheet(
            css=stylesheet.css,
            base_url=document_base,
            embedded=True,
            media=stylesheet.media,
        )
        for stylesheet in inspected.stylesheets
    )
    stylesheet_snapshot = (*external_stylesheets, *embedded_stylesheets)
    requirements: set[RenderRequirement] = set()

    if inspected.has_script:
        requirements.add(RenderRequirement.JAVASCRIPT)
    for reference in inspected.references:
        requirement = _resource_requirement(reference, base_url=document_base)
        if requirement is not None:
            requirements.add(requirement)
    for stylesheet in external_stylesheets:
        for reference in css_resource_references(stylesheet.css):
            requirement = _resource_requirement(
                reference,
                base_url=stylesheet.base_url,
            )
            if requirement is not None:
                requirements.add(requirement)

    return PreparedHtml(
        html=html,
        stylesheets=stylesheet_snapshot,
        base_url=base_url,
        assets=tuple(assets),
        requirements=frozenset(requirements),
    )


__all__ = ("prepare_html",)
