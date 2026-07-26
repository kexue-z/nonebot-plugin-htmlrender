"""Prepare arbitrary HTML while preserving browser and native execution forms."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from nonebot_plugin_htmlrender.errors import PreparationError

from .models import (
    DocumentBase,
    DocumentStructureSnapshot,
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


def _prepare_html(
    html: str,
    *,
    base_url: str | None = None,
    stylesheets: Iterable[str | PreparedStylesheet] = (),
    assets: Iterable[PreparedAsset] = (),
) -> PreparedHtml:
    """Build a canonical payload without performing backend-specific transport."""

    if base_url is not None:
        urlsplit(base_url)
    inspected = inspect_html_references(html, base_url=base_url)
    # The single place that parses the markup; materialization and adapters
    # read ``PreparedHtml.document_base``/``structure`` instead of re-parsing.
    document_base_value = DocumentBase(
        declared_href=inspected.base_href,
        preparation_base_url=base_url,
    )
    document_base = document_base_value.resolve()
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
        assets=tuple(assets),
        requirements=frozenset(requirements),
        document_base=document_base_value,
        structure=DocumentStructureSnapshot(
            references=tuple(inspected.references),
            linked_stylesheets=tuple(inspected.linked_stylesheets),
            has_script=inspected.has_script,
            base_tag=inspected.base_tag,
            head_open_end=inspected.head_open_end,
            doctype_end=inspected.doctype_end,
        ),
    )


def prepare_html(
    html: str,
    *,
    base_url: str | None = None,
    stylesheets: Iterable[str | PreparedStylesheet] = (),
    assets: Iterable[PreparedAsset] = (),
) -> PreparedHtml:
    """Build a canonical payload without performing backend-specific transport."""
    try:
        return _prepare_html(
            html,
            base_url=base_url,
            stylesheets=stylesheets,
            assets=assets,
        )
    except PreparationError:
        raise
    except ValueError as error:
        raise PreparationError(
            "Invalid HTML preparation input.",
            source=error,
        ) from error


__all__ = ("prepare_html",)
