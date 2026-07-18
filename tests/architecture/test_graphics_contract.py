from __future__ import annotations

from nonebot_plugin_htmlrender.graphics import (
    PILLOW_RASTER_SCENE_RENDERER,
    SKIA_RASTER_SCENE_RENDERER,
)
from nonebot_plugin_htmlrender.providers.sdk import (
    HTMLKIT_PROVIDER_ID,
    PLAYWRIGHT_PROVIDER_ID,
    RESERVED_PROVIDER_IDS,
    TAKUMI_PROVIDER_ID,
)


def test_graphics_backends_are_not_html_engine_identifiers() -> None:
    html_backends = {
        HTMLKIT_PROVIDER_ID,
        PLAYWRIGHT_PROVIDER_ID,
        TAKUMI_PROVIDER_ID,
    }

    assert "htmlkit" in html_backends
    assert "htmlkit" in RESERVED_PROVIDER_IDS
    assert "pillow" not in html_backends
    assert "skia" not in html_backends
    assert "pillow" not in RESERVED_PROVIDER_IDS
    assert "skia" not in RESERVED_PROVIDER_IDS


def test_graphics_capability_names_do_not_share_provider_namespace() -> None:
    assert PILLOW_RASTER_SCENE_RENDERER.name.startswith("graphics.pillow.")
    assert SKIA_RASTER_SCENE_RENDERER.name.startswith("graphics.skia.")
