from nonebot_plugin_htmlrender.backend.playwright.models import (
    JpegScreenshotOptions,
    PngScreenshotOptions,
    create_jpeg_config,
    create_png_config,
)
from nonebot_plugin_htmlrender.utils import signal as html_signal
from nonebot_plugin_htmlrender.utils import telemetry as html_telemetry
from nonebot_plugin_htmlrender.utils.signal import (
    HANDLED_SIGNALS,
    install_signal_handler,
    register_signal_handler,
    remove_signal_handler,
    shield_signals,
)
from nonebot_plugin_htmlrender.utils.telemetry import track_render


def test_models_create_png_and_jpeg_config() -> None:
    png_default = create_png_config()
    png_hq = create_png_config(
        quality_optimized=True,
        viewport_width=1024,
        viewport_height=768,
    )
    jpeg = create_jpeg_config(
        quality=66,
        viewport_width=640,
        viewport_height=360,
    )

    assert isinstance(png_default.screenshot, PngScreenshotOptions)
    assert png_default.screenshot.device_scale_factor == 2.0
    assert isinstance(png_hq.screenshot, PngScreenshotOptions)
    assert png_hq.screenshot.device_scale_factor == 3.0
    assert png_hq.page.viewport.width == 1024
    assert png_hq.page.viewport.height == 768

    assert isinstance(jpeg.screenshot, JpegScreenshotOptions)
    assert jpeg.screenshot.quality == 66
    assert jpeg.page.viewport.width == 640
    assert jpeg.page.viewport.height == 360


def test_signal_module_reexports_utils_symbols() -> None:
    assert html_signal.HANDLED_SIGNALS == HANDLED_SIGNALS
    assert html_signal.install_signal_handler is install_signal_handler
    assert html_signal.register_signal_handler is register_signal_handler
    assert html_signal.remove_signal_handler is remove_signal_handler
    assert html_signal.shield_signals is shield_signals
    assert set(html_signal.__all__) == {
        "HANDLED_SIGNALS",
        "install_signal_handler",
        "register_signal_handler",
        "remove_signal_handler",
        "shield_signals",
    }


def test_telemetry_module_reexports_track_render() -> None:
    assert html_telemetry.track_render is track_render
