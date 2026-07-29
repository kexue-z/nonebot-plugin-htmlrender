"""Process-default Application holder.

The NoneBot bootstrap installs a lazy application factory here; the first
convenience call builds and retains the process-default object graph. This
holder is the only process-level state in the render object graph.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.rendering.errors import ApplicationNotInitialized

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot_plugin_htmlrender.application import Application, Renderer

_default_application: Application | None = None
_default_factory: Callable[[], Application] | None = None
_build_lock = threading.Lock()


def set_default_application(
    application: Application | None,
) -> Application | None:
    """Install the process default application; returns the previous one."""
    global _default_application  # noqa: PLW0603
    previous = _default_application
    _default_application = application
    return previous


def set_default_application_factory(
    factory: Callable[[], Application] | None,
) -> Callable[[], Application] | None:
    """Install a lazy builder used on first default-application access.

    The factory keeps heavy engine imports off the plugin import path for
    ``startup: off`` deployments; it runs at most once.
    """
    global _default_factory  # noqa: PLW0603
    previous = _default_factory
    _default_factory = factory
    return previous


def peek_default_application() -> Application | None:
    """Return the default application only if it has been built already."""
    return _default_application


def get_default_application() -> Application:
    """Return the process default application composed by the bootstrap."""
    global _default_application  # noqa: PLW0603
    application = _default_application
    if application is not None:
        return application
    factory = _default_factory
    if factory is None:
        raise ApplicationNotInitialized(
            "htmlrender is not initialized: load the NoneBot plugin or install "
            "a default application via set_default_application()."
        )
    with _build_lock:
        if _default_application is None:
            _default_application = factory()
        return _default_application


def get_default_renderer() -> Renderer:
    """Return the renderer of the process default application."""
    return get_default_application().renderer
