"""Stable error model exposed at the rendering application boundary.

Every native or provider-specific exception is translated into one of these
types at the adapter boundary; callers never see engine exceptions.
"""

from __future__ import annotations


class RenderingError(Exception):
    """Base class for every error raised by the rendering application."""


class InvalidRenderRequest(RenderingError):
    """A render request carries values that can never execute successfully."""


class CapabilityUnavailable(RenderingError):
    """A requested capability has no binding in the current composition."""

    def __init__(self, capability: str, *, detail: str | None = None) -> None:
        message = f"Capability `{capability}` is not available in this composition."
        if detail:
            message = f"{message} {detail}"
        super().__init__(message)
        self.capability = capability


class UnsupportedRequirement(RenderingError):
    """The prepared document needs something the provider cannot deliver."""


class ProviderNotConfigured(RenderingError):
    """No provider is selected in the runtime configuration."""


class ProviderNotFound(RenderingError):
    """The configured provider id does not resolve to any known provider."""


class ProviderUnavailable(RenderingError):
    """The provider exists but cannot run in the current environment."""


class ProviderExecutionError(RenderingError):
    """The provider failed while executing a render operation."""


class ProviderLifecycleError(RenderingError):
    """The provider runtime failed to start, probe, or shut down."""


class ResourceResolutionError(RenderingError):
    """A referenced resource could not be resolved for rendering."""


class ResourceAccessDenied(ResourceResolutionError):
    """The referenced resource is outside the allowed local access policy."""


class ResourceNotFound(ResourceResolutionError):
    """The referenced resource does not exist."""


class ResourceSizeExceeded(ResourceResolutionError):
    """The referenced resource exceeds the configured size budget."""
