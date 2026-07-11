"""Backend-neutral content preparation facade."""

from .content import (
    MARKDOWN_TEMPLATE_FILE,
    MARKDOWN_TEMPLATES_PATH,
    TEMPLATES_PATH,
    TEXT_TEMPLATE_FILE,
    TEXT_TEMPLATES_PATH,
    prepare_markdown,
    prepare_template,
    prepare_text,
)
from .html import prepare_html
from .models import PreparedAsset, PreparedHtml, RasterOptions, RenderRequirement

__all__ = (
    "MARKDOWN_TEMPLATES_PATH",
    "MARKDOWN_TEMPLATE_FILE",
    "TEMPLATES_PATH",
    "TEXT_TEMPLATES_PATH",
    "TEXT_TEMPLATE_FILE",
    "PreparedAsset",
    "PreparedHtml",
    "RasterOptions",
    "RenderRequirement",
    "prepare_html",
    "prepare_markdown",
    "prepare_template",
    "prepare_text",
)
