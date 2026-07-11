"""Resolve resource references inside HTML documents."""

from __future__ import annotations

from html import unescape
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.resources.template import (
    resolve_url_tokens,
    should_resolve_resources,
)

from .references import inspect_html_references, rewrite_html_references

if TYPE_CHECKING:
    from pathlib import Path

    from nonebot_plugin_htmlrender.resources.resolve import ResourceResolver


async def resolve_html_resources(
    html: str,
    *,
    template_base: str | Path | None = None,
    strict: bool = False,
    resolver: ResourceResolver | str | None = None,
    lease_id: str | None = None,
) -> str:
    """Resolve real HTML/CSS resource tokens without scanning comments/scripts."""
    if not should_resolve_resources(resolver):
        return html

    references = tuple(dict.fromkeys(inspect_html_references(html).references))
    resolved_values = await resolve_url_tokens(
        references,
        template_base=template_base,
        strict=strict,
        resolver=resolver,
        lease_id=lease_id,
    )
    replacements = dict(zip(references, resolved_values, strict=True))

    def rewrite(reference: str) -> str | None:
        replacement = replacements.get(reference)
        if replacement is not None:
            return replacement
        return replacements.get(unescape(reference))

    return rewrite_html_references(html, rewrite)


__all__ = ["resolve_html_resources"]
