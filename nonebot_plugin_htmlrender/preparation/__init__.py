"""Backend-neutral preparation domain and pure HTML canonicalization."""

from .html import prepare_html
from .models import (
    PreparedAsset,
    PreparedHtml,
    PreparedStylesheet,
    RasterOptions,
    RenderRequirement,
)
from .service import DefaultHtmlPreparer, HtmlPreparer, PreparationService

__all__ = (
    "DefaultHtmlPreparer",
    "HtmlPreparer",
    "PreparationService",
    "PreparedAsset",
    "PreparedHtml",
    "PreparedStylesheet",
    "RasterOptions",
    "RenderRequirement",
    "prepare_html",
)
