"""Typed first-party extensions exposed by an application."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, final

from nonebot_plugin_htmlrender.capabilities import (
    PLAYWRIGHT,
    TAKUMI,
    PlaywrightAccess,
    TakumiAccess,
)
from nonebot_plugin_htmlrender.graphics.capabilities import (
    PILLOW_RASTER_SCENE_RENDERER,
    SKIA_RASTER_SCENE_RENDERER,
)

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.graphics.ports import RasterSceneRenderer
    from nonebot_plugin_htmlrender.rendering.capabilities import (
        CapabilityCatalog,
        CapabilityKey,
    )

T = TypeVar("T")


@final
class ApplicationExtensions:
    """Typed first-party access with a generic third-party fallback."""

    __slots__ = ("_catalog",)

    def __init__(self, catalog: CapabilityCatalog) -> None:
        self._catalog = catalog

    @property
    def playwright(self) -> PlaywrightAccess:
        return self._catalog.require(PLAYWRIGHT)

    @property
    def takumi(self) -> TakumiAccess:
        return self._catalog.require(TAKUMI)

    @property
    def pillow(self) -> RasterSceneRenderer:
        return self._catalog.require(PILLOW_RASTER_SCENE_RENDERER)

    @property
    def skia(self) -> RasterSceneRenderer:
        return self._catalog.require(SKIA_RASTER_SCENE_RENDERER)

    def get(self, key: CapabilityKey[T]) -> T | None:
        """Resolve an optional extension registered under a custom key."""
        return self._catalog.get(key)

    def require(self, key: CapabilityKey[T]) -> T:
        """Resolve a required extension registered under a custom key."""
        return self._catalog.require(key)

    def names(self) -> frozenset[str]:
        return self._catalog.names()

    def __contains__(self, key: object) -> bool:
        return key in self._catalog


__all__ = ["ApplicationExtensions"]
