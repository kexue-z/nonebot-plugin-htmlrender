"""Neutral render request value objects shared by every engine.

Requests only express cross-engine semantics: content sources, raster
options, resource base and per-call resource policy, operation timeout, and
template inputs. Provider-specific knobs (navigation, user agent, browser
options, selector capture, native node APIs) live in provider capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.preparation.models import RasterOptions
from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode

from .errors import InvalidRenderRequest


def _frozen_template_inputs(
    variables: Mapping[str, object],
    filters: Mapping[str, FilterCallable] | None,
) -> tuple[Mapping[str, object], Mapping[str, FilterCallable] | None]:
    """Snapshot template mappings so a request cannot be mutated in flight.

    The top-level containers are copied into read-only views, so a concurrent
    caller can no longer add, remove or replace keys while the request is
    executing. Value objects are not deep-copied.
    """
    frozen_variables = MappingProxyType(dict(variables))
    frozen_filters = None if filters is None else MappingProxyType(dict(filters))
    return frozen_variables, frozen_filters


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
    """Skip local resource resolution and materialization for this execution."""


# The single source of truth for translating per-call policies into
# preparation/execution resolve modes.  Renaming a member on either enum must
# fail here instead of silently matching through shared value strings.
POLICY_RESOLVE_MODES: dict[ResourcePolicy, ResourceResolveMode] = {
    ResourcePolicy.AUTO: ResourceResolveMode.AUTO,
    ResourcePolicy.STRICT: ResourceResolveMode.STRICT,
    ResourcePolicy.OFF: ResourceResolveMode.OFF,
}


def resolve_mode_for_policy(policy: ResourcePolicy) -> ResourceResolveMode:
    return POLICY_RESOLVE_MODES[policy]


def effective_resource_resolve_mode(
    policy: ResourcePolicy | None,
    default: ResourceResolveMode,
) -> ResourceResolveMode:
    """Resolve a per-call override against the provider-selected default."""
    if policy is None:
        return default
    return resolve_mode_for_policy(policy)


def _validate_timeout(timeout_seconds: float | None) -> None:
    if timeout_seconds is not None and (
        not math.isfinite(timeout_seconds) or timeout_seconds <= 0
    ):
        raise InvalidRenderRequest(
            "timeout_seconds must be finite and positive when provided."
        )


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
    resource_policy: ResourcePolicy | None = None
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
        variables, filters = _frozen_template_inputs(self.variables, self.filters)
        object.__setattr__(self, "variables", variables)
        object.__setattr__(self, "filters", filters)
        object.__setattr__(self, "extensions", tuple(self.extensions))


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
        variables, filters = _frozen_template_inputs(self.variables, self.filters)
        object.__setattr__(self, "variables", variables)
        object.__setattr__(self, "filters", filters)
        object.__setattr__(self, "extensions", tuple(self.extensions))


@dataclass(frozen=True, slots=True)
class RasterizeHtmlRequest:
    """Execute an already prepared HTML document into a raster image."""

    prepared: PreparedHtml
    options: RasterOptions = field(default_factory=RasterOptions)
    resource_policy: ResourcePolicy | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        _validate_timeout(self.timeout_seconds)
