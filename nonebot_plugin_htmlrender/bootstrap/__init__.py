"""NoneBot composition root: unified config, object graph, lifecycle hooks."""

from .composition import ComposedRuntime as ComposedRuntime
from .composition import prepare_runtime as prepare_runtime
from .settings import GraphicsSettings as GraphicsSettings
from .settings import RenderPluginConfig as RenderPluginConfig
from .settings import RenderSettings as RenderSettings
from .settings import load_render_settings as load_render_settings

__all__ = [
    "ComposedRuntime",
    "GraphicsSettings",
    "RenderPluginConfig",
    "RenderSettings",
    "load_render_settings",
    "prepare_runtime",
]
