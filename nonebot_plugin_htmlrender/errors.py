"""Lowest-level public error root shared by all architectural layers."""


class RenderingError(Exception):
    """Base class for every error exposed by the rendering application."""


class InvalidRenderRequest(RenderingError):
    """A public operation received values that cannot be processed."""


class PreparationError(RenderingError):
    """Backend-neutral content preparation failed."""


__all__ = ["InvalidRenderRequest", "PreparationError", "RenderingError"]
