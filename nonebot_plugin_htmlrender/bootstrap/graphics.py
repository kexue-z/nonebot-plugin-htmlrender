"""Composition of independent in-process raster-scene capabilities."""

from __future__ import annotations

from importlib.util import find_spec
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.graphics.capabilities import (
    PILLOW_RASTER_SCENE_RENDERER,
    SKIA_RASTER_SCENE_RENDERER,
)
from nonebot_plugin_htmlrender.graphics.errors import RasterBackendUnavailable
from nonebot_plugin_htmlrender.graphics.execution import RasterWorkBudget
from nonebot_plugin_htmlrender.rendering.capabilities import CapabilityCatalog

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.graphics.models import GraphicsBackendName
    from nonebot_plugin_htmlrender.rendering.admission import OperationAdmissionGate
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from nonebot_plugin_htmlrender.resources.ports import WorkerExecutor

    from .settings import GraphicsSettings


def _require_module(
    backend: GraphicsBackendName,
    module: str,
    extra: str,
) -> None:
    try:
        available = find_spec(module) is not None
    except (ImportError, ValueError):
        available = False
    if not available:
        raise RasterBackendUnavailable(
            backend,
            f"install nonebot-plugin-htmlrender[{extra}]",
        )


def build_graphics_capabilities(
    settings: GraphicsSettings,
    *,
    worker: WorkerExecutor,
    observer: OperationObserver,
    operation_admission: OperationAdmissionGate,
) -> CapabilityCatalog:
    """Build only the explicitly configured Pillow/Skia capabilities."""
    catalog = CapabilityCatalog()
    if not settings.backends:
        return catalog

    budget = RasterWorkBudget(
        max_pixels=settings.max_pixels,
        max_concurrency=settings.max_concurrency,
        max_commands=settings.max_commands,
    )
    for backend in settings.backends:
        if backend == "pillow":
            _require_module("pillow", "PIL", "pillow")
            try:
                from nonebot_plugin_htmlrender.adapters.pillow import (  # noqa: PLC0415
                    PillowRasterSceneRenderer,
                )
            except ImportError as error:
                raise RasterBackendUnavailable(
                    "pillow",
                    "adapter import failed",
                    source=error,
                ) from error
            catalog = catalog.with_capability(
                PILLOW_RASTER_SCENE_RENDERER,
                PillowRasterSceneRenderer(
                    worker=worker,
                    observer=observer,
                    operation_admission=operation_admission,
                    budget=budget,
                ),
            )
        elif backend == "skia":
            _require_module("skia", "skia", "skia")
            try:
                from nonebot_plugin_htmlrender.adapters.skia import (  # noqa: PLC0415
                    SkiaRasterSceneRenderer,
                )
            except ImportError as error:
                raise RasterBackendUnavailable(
                    "skia",
                    "adapter import failed",
                    source=error,
                ) from error
            catalog = catalog.with_capability(
                SKIA_RASTER_SCENE_RENDERER,
                SkiaRasterSceneRenderer(
                    worker=worker,
                    observer=observer,
                    operation_admission=operation_admission,
                    budget=budget,
                ),
            )
        else:
            raise RasterBackendUnavailable(
                backend,
                "unknown graphics backend; expected 'pillow' or 'skia'",
            )
    return catalog


__all__ = ["build_graphics_capabilities"]
