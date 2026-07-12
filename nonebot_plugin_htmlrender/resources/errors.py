"""Stable failures owned by the resource domain."""

from nonebot_plugin_htmlrender.errors import RenderingError


class ResourceResolutionError(RenderingError):
    """A referenced resource could not be resolved for rendering."""


class ResourceAccessDenied(ResourceResolutionError):
    """The referenced resource is outside the allowed local access policy."""


class ResourceNotFound(ResourceResolutionError):
    """The referenced resource does not exist."""


class ResourceSizeExceeded(ResourceResolutionError):
    """The referenced resource exceeds the configured size budget."""


__all__ = [
    "ResourceAccessDenied",
    "ResourceNotFound",
    "ResourceResolutionError",
    "ResourceSizeExceeded",
]
