"""Immutable use-case bindings consumed by the renderer."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .use_cases import (
        RasterizeHtml,
        RenderHtml,
        RenderMarkdown,
        RenderTemplate,
        RenderTemplateHtml,
        RenderText,
    )


@dataclass(frozen=True, slots=True)
class RendererBindings:
    """Use cases actually available in one composition.

    Renderer capability presence is derived from which bindings are set;
    there is no separate capability declaration to keep in sync.
    """

    render_html: RenderHtml | None = None
    render_text: RenderText | None = None
    render_markdown: RenderMarkdown | None = None
    render_template: RenderTemplate | None = None
    render_template_html: RenderTemplateHtml | None = None
    rasterize_html: RasterizeHtml | None = None

    def present(self) -> frozenset[str]:
        """Names of the bound use cases."""
        return frozenset(
            binding.name
            for binding in fields(self)
            if getattr(self, binding.name) is not None
        )
