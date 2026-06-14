from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_core_config_logs_when_backend_is_not_set(mocker: MockerFixture) -> None:
    import nonebot_plugin_htmlrender.config as core_config  # noqa: PLC0415

    logger_info = mocker.patch.object(core_config.logger, "info")

    cfg = core_config.Config.model_validate({})

    assert cfg.render_backend is None
    logger_info.assert_called_once_with(
        "[htmlrender] render_backend is not set; runtime startup will be skipped."
    )


def test_core_config_does_not_log_when_backend_is_set(mocker: MockerFixture) -> None:
    import nonebot_plugin_htmlrender.config as core_config  # noqa: PLC0415
    from nonebot_plugin_htmlrender.consts import (  # noqa: PLC0415
        RenderBackend,
        RenderStartupMode,
    )

    logger_info = mocker.patch.object(core_config.logger, "info")

    cfg = core_config.Config.model_validate({"render_backend": "playwright"})

    assert cfg.render_backend is RenderBackend.PLAYWRIGHT
    assert cfg.render_startup_mode is RenderStartupMode.OFF
    logger_info.assert_not_called()


def test_playwright_config_get_helper_supports_dict_and_object() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        _get,
    )

    assert _get({"name": "dict-value"}, "name") == "dict-value"
    assert _get(SimpleNamespace(name="object-value"), "name") == "object-value"
    assert _get(None, "name", "fallback") == "fallback"
