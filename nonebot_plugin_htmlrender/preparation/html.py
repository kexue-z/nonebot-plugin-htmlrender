"""Prepare arbitrary HTML while preserving browser and native execution forms."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .models import PreparedAsset, PreparedHtml, RenderRequirement

if TYPE_CHECKING:
    from collections.abc import Iterable

_STYLE_RE = re.compile(
    r"<style\b[^>]*>(?P<css>.*?)</style\s*>",
    re.IGNORECASE | re.DOTALL,
)
_SCRIPT_RE = re.compile(r"<script\b", re.IGNORECASE)
_RESOURCE_URL_RE = re.compile(
    r"(?:\b(?:src|href|poster)\s*=\s*['\"](?P<attr>[^'\"]+)['\"]|"
    r"url\(\s*['\"]?(?P<css>[^)'\"]+)['\"]?\s*\))",
    re.IGNORECASE,
)
_CSS_IMPORT_RE = re.compile(r"@import\s+(?:url\()?\s*['\"]?", re.IGNORECASE)


def _resource_requirement(value: str) -> RenderRequirement | None:
    stripped = value.strip()
    if not stripped or stripped.startswith(("data:", "memory:", "#")):
        return None
    parsed = urlsplit(stripped)
    if parsed.scheme in {"http", "https"}:
        return RenderRequirement.NETWORK
    if parsed.scheme == "file" or not parsed.scheme:
        return RenderRequirement.LOCAL_RESOURCE
    return None


def prepare_html(
    html: str,
    *,
    base_url: str | None = None,
    stylesheets: Iterable[str] = (),
    assets: Iterable[PreparedAsset] = (),
) -> PreparedHtml:
    """Build a canonical payload without performing backend-specific transport."""
    extracted_styles = tuple(match.group("css") for match in _STYLE_RE.finditer(html))
    markup = _STYLE_RE.sub("", html)
    stylesheet_snapshot = (*tuple(stylesheets), *extracted_styles)
    requirements: set[RenderRequirement] = set()

    if _SCRIPT_RE.search(html):
        requirements.add(RenderRequirement.JAVASCRIPT)
    for match in _RESOURCE_URL_RE.finditer(html):
        value = match.group("attr") or match.group("css") or ""
        requirement = _resource_requirement(value)
        if requirement is not None:
            requirements.add(requirement)
    for stylesheet in stylesheet_snapshot:
        for match in _RESOURCE_URL_RE.finditer(stylesheet):
            value = match.group("attr") or match.group("css") or ""
            requirement = _resource_requirement(value)
            if requirement is not None:
                requirements.add(requirement)
    if any(_CSS_IMPORT_RE.search(stylesheet) for stylesheet in stylesheet_snapshot):
        requirements.add(RenderRequirement.NETWORK)

    return PreparedHtml(
        html=html,
        markup=markup,
        stylesheets=stylesheet_snapshot,
        base_url=base_url,
        assets=tuple(assets),
        requirements=frozenset(requirements),
    )


__all__ = ("prepare_html",)
