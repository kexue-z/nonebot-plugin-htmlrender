"""Stable errors for neutral requests, lifecycles, and executor boundaries.

Provider-specific typed capabilities may intentionally expose their engine's
native exceptions; the neutral executor boundary translates those failures.
"""

from __future__ import annotations

from nonebot_plugin_htmlrender.errors import (
    ErrorCause as ErrorCause,
)
from nonebot_plugin_htmlrender.errors import (
    InvalidRenderRequest as InvalidRenderRequest,
)
from nonebot_plugin_htmlrender.errors import PreparationError as PreparationError
from nonebot_plugin_htmlrender.errors import RenderingError as RenderingError
from nonebot_plugin_htmlrender.resources.errors import (
    ResourceAccessDenied as ResourceAccessDenied,
)
from nonebot_plugin_htmlrender.resources.errors import (
    ResourceNotFound as ResourceNotFound,
)
from nonebot_plugin_htmlrender.resources.errors import (
    ResourceResolutionError as ResourceResolutionError,
)
from nonebot_plugin_htmlrender.resources.errors import (
    ResourceSizeExceeded as ResourceSizeExceeded,
)


class CapabilityUnavailable(RenderingError):
    """A requested capability has no binding in the current composition."""

    def __init__(self, capability: str, *, detail: str | None = None) -> None:
        message = f"Capability `{capability}` is not available in this composition."
        if detail:
            message = f"{message} {detail}"
        super().__init__(message)
        self.capability = capability


class ApplicationNotInitialized(RenderingError):
    """The process-default Application has not been installed by a host."""


class UnsupportedRequirement(RenderingError):
    """The prepared document needs something the provider cannot deliver."""


class UnsupportedRenderOption(RenderingError):
    """A valid portable raster option is unsupported by the selected provider."""


class ProviderNotFound(RenderingError):
    """The configured provider id does not resolve to any known provider."""


class ProviderUnavailable(RenderingError):
    """The provider exists but cannot run in the current environment."""


class ProviderExecutionError(RenderingError):
    """The provider failed while executing a render operation."""


class ProviderLifecycleError(RenderingError):
    """The provider runtime failed to start, probe, or shut down."""
