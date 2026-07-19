"""Backend-neutral documents produced before renderer-specific execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest

# Keep public annotations resolvable through typing.get_type_hints().
from nonebot_plugin_htmlrender.raster import RasterImageFormat  # noqa: TC001

from .assets import resolve_document_reference


class RenderRequirement(str, Enum):
    """Execution features required by prepared content."""

    JAVASCRIPT = "javascript"
    NETWORK = "network"
    LOCAL_RESOURCE = "local_resource"


@dataclass(frozen=True, slots=True)
class DocumentBase:
    """Resolved document-base semantics carried by a prepared document.

    ``declared_href`` is the value of an in-document ``<base href>`` parsed
    once by ``prepare_html``: ``None`` means no ``<base href>`` was declared,
    while an empty string is an explicit ``<base href="">`` that resolves to
    the document URL itself. ``preparation_base_url`` is the base URL the
    document was prepared with. ``resolve`` combines them with an optional
    execution-time fallback so every consumer derives one canonical base
    instead of re-parsing the markup.
    """

    declared_href: str | None = None
    preparation_base_url: str | None = None

    def resolve(self, fallback_base_url: str | None = None) -> str | None:
        root = self.preparation_base_url or fallback_base_url
        if self.declared_href is not None:
            # An explicit empty href resolves to the document URL itself.
            return resolve_document_reference(root, self.declared_href) or root
        return root


@dataclass(frozen=True, slots=True)
class DocumentStructureSnapshot:
    """Structural facts extracted by the single preparation-time HTML parse.

    Offsets index into the exact ``PreparedHtml.html`` string, so execution
    can canonicalize the document base and inject head content by pure
    string splicing without parsing the markup again.
    """

    references: tuple[str, ...] = ()
    linked_stylesheets: tuple[str, ...] = ()
    has_script: bool = False
    base_tag: tuple[int, int, str] | None = None
    """``(start, end, raw)`` span of the first ``<base>`` carrying ``href``."""
    head_open_end: int | None = None
    doctype_end: int | None = None


@dataclass(frozen=True, slots=True)
class PreparedAsset:
    """Binary resource addressable by its exact document URL."""

    source: str
    data: bytes
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedStylesheet:
    """One stylesheet with its own resource-resolution base."""

    css: str
    base_url: str | None = None
    embedded: bool = False
    media: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedHtml:
    """Canonical HTML payload shared by browser and native renderers.

    ``html`` always retains the original browser document. Build instances
    through :func:`nonebot_plugin_htmlrender.preparation.prepare_html` — the
    sole place that parses the markup; ``document_base`` and ``structure``
    are that parse's results and consumers never re-derive them. The
    resource-resolution root lives in ``document_base.preparation_base_url``.
    """

    html: str
    stylesheets: tuple[PreparedStylesheet, ...] = ()
    assets: tuple[PreparedAsset, ...] = ()
    requirements: frozenset[RenderRequirement] = field(default_factory=frozenset)
    document_base: DocumentBase = field(kw_only=True)
    """Document-base semantics fixed at preparation time.

    Consumers call ``document_base.resolve(fallback_base_url=...)`` instead of
    re-deriving the base from the markup.
    """
    structure: DocumentStructureSnapshot = field(kw_only=True)
    """Reference and insertion-point facts for the exact ``html`` string."""


@dataclass(frozen=True, slots=True)
class RasterOptions:
    """Portable raster options shared by HTML-capable engines."""

    width: int = 800
    height: int | None = None
    device_pixel_ratio: float = 2.0
    format: RasterImageFormat = "png"
    quality: int | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or (self.height is not None and self.height <= 0):
            raise InvalidRenderRequest("Raster dimensions must be positive")
        if not math.isfinite(self.device_pixel_ratio) or self.device_pixel_ratio <= 0:
            raise InvalidRenderRequest("device_pixel_ratio must be finite and positive")
        if self.format not in {"png", "jpeg"}:
            raise InvalidRenderRequest("format must be 'png' or 'jpeg'")
        if self.quality is not None and self.format != "jpeg":
            raise InvalidRenderRequest("quality is only supported for JPEG output")
        if self.quality is not None and not 0 <= self.quality <= 100:
            raise InvalidRenderRequest("quality must be between 0 and 100")


__all__ = (
    "DocumentBase",
    "DocumentStructureSnapshot",
    "PreparedAsset",
    "PreparedHtml",
    "PreparedStylesheet",
    "RasterOptions",
    "RenderRequirement",
)
