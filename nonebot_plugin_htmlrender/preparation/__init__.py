"""Backend-neutral content preparation facade."""

from .content import prepare_markdown, prepare_template, prepare_text
from .html import prepare_html
from .models import (
    PreparedAsset,
    PreparedHtml,
    PreparedStylesheet,
    RasterOptions,
    RenderRequirement,
)
from .resolve import resolve_html_resources
from .template_assets import stage_template_variables

__all__ = (
    "PreparedAsset",
    "PreparedHtml",
    "PreparedStylesheet",
    "RasterOptions",
    "RenderRequirement",
    "prepare_html",
    "prepare_markdown",
    "prepare_template",
    "prepare_text",
    "resolve_html_resources",
    "stage_template_variables",
)
