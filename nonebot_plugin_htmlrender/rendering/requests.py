"""Neutral render request value objects shared by every engine.

Requests only express cross-engine semantics: content sources, raster
options, resource base and per-call resource policy, operation timeout, and
template inputs. Provider-specific knobs (navigation, user agent, browser
options, selector capture, native node APIs) live in provider capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.preparation.models import RasterOptions

from .errors import InvalidRenderRequest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml
    from nonebot_plugin_htmlrender.resources.templating import (
        ExtensionSpec,
        FilterCallable,
    )


class ResourcePolicy(str, Enum):
    """Per-call policy for resolving local resources referenced by content."""

    AUTO = "auto"
    """Resolve local resources, tolerating unresolvable references."""

    STRICT = "strict"
    """Resolve local resources and fail on any unresolvable reference."""

    OFF = "off"
    """Skip preparation-time local resource resolution."""


def _validate_timeout(timeout_seconds: float | None) -> None:
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise InvalidRenderRequest("timeout_seconds must be positive when provided.")


@dataclass(frozen=True, slots=True)
class RenderHtmlRequest:
    """Render an HTML document into a raster image."""

    html: str
    raster: RasterOptions = field(default_factory=RasterOptions)
    base_url: str | None = None
    resource_policy: ResourcePolicy | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        _validate_timeout(self.timeout_seconds)


@dataclass(frozen=True, slots=True)
class RenderTextRequest:
    """Render plain text into a raster image."""

    text: str
    css_path: str = ""
    raster: RasterOptions = field(default_factory=RasterOptions)
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        _validate_timeout(self.timeout_seconds)


@dataclass(frozen=True, slots=True)
class RenderMarkdownRequest:
    """Render Markdown content into a raster image."""

    markdown: str = ""
    markdown_path: str = ""
    css_path: str = ""
    raster: RasterOptions = field(default_factory=RasterOptions)
    resource_policy: ResourcePolicy | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.markdown and not self.markdown_path:
            raise InvalidRenderRequest(
                "Either markdown or markdown_path must be provided."
            )
        _validate_timeout(self.timeout_seconds)


@dataclass(frozen=True, slots=True)
class RenderTemplateRequest:
    """Render a Jinja template into a raster image."""

    template_path: str | Path
    template_name: str
    variables: Mapping[str, object] = field(default_factory=dict)
    filters: Mapping[str, FilterCallable] | None = None
    extensions: Sequence[ExtensionSpec] = ()
    raster: RasterOptions = field(default_factory=RasterOptions)
    resource_policy: ResourcePolicy | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.template_name:
            raise InvalidRenderRequest("template_name must not be empty.")
        _validate_timeout(self.timeout_seconds)


@dataclass(frozen=True, slots=True)
class RenderTemplateHtmlRequest:
    """Render a Jinja template into an HTML string."""

    template_path: str | Path
    template_name: str
    variables: Mapping[str, object] = field(default_factory=dict)
    filters: Mapping[str, FilterCallable] | None = None
    extensions: Sequence[ExtensionSpec] = ()

    def __post_init__(self) -> None:
        if not self.template_name:
            raise InvalidRenderRequest("template_name must not be empty.")


@dataclass(frozen=True, slots=True)
class RasterizeHtmlRequest:
    """Execute an already prepared HTML document into a raster image."""

    prepared: PreparedHtml
    options: RasterOptions = field(default_factory=RasterOptions)
    resource_policy: ResourcePolicy | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        _validate_timeout(self.timeout_seconds)
