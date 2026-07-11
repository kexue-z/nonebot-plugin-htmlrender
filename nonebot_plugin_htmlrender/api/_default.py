"""Process-default Application holder.

The NoneBot bootstrap composes the object graph once and installs it here;
the convenience functions resolve through these accessors. This is one of
the two sanctioned process-level singletons (the other being the provider
discovery cache).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.rendering.errors import ProviderNotConfigured

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.application import Application, Renderer

_default_application: Application | None = None


def set_default_application(
    application: Application | None,
) -> Application | None:
    """Install the process default application; returns the previous one."""
    global _default_application  # noqa: PLW0603
    previous = _default_application
    _default_application = application
    return previous


def get_default_application() -> Application:
    """Return the process default application composed by the bootstrap."""
    if _default_application is None:
        raise ProviderNotConfigured(
            "htmlrender is not initialized: load the NoneBot plugin or install "
            "a default application via set_default_application()."
        )
    return _default_application


def get_default_renderer() -> Renderer:
    """Return the renderer of the process default application."""
    return get_default_application().renderer
