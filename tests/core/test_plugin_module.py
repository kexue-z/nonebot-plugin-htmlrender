from __future__ import annotations

from importlib import import_module
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import call

import pytest

import nonebot_plugin_htmlrender as plugin
from nonebot_plugin_htmlrender import _bootstrap
from nonebot_plugin_htmlrender.consts import RenderBackend, RenderStartupMode

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_plugin_import_bootstraps_telemetry_plugins(mocker: MockerFixture) -> None:
    mocker.patch.object(_bootstrap, "find_spec", return_value=object())
    require = mocker.patch.object(_bootstrap, "require")
    patch_filehost = mocker.patch.object(
        _bootstrap, "_patch_filehost_request_headers_validator"
    )

    plugin._bootstrap_optional_plugins_on_import()

    assert require.call_args_list == [
        call("nonebot_plugin_sentry"),
        call("nonebot_plugin_prometheus"),
    ]
    patch_filehost.assert_not_called()


def test_patch_filehost_request_headers_validator_for_pydantic_v2_compat(
    mocker: MockerFixture,
) -> None:
    class _Headers:
        @classmethod
        def validate(cls, value):
            return {"value": value}

    class _ScopeInfo:
        rebuilt = False

        @classmethod
        def model_rebuild(cls, *, force: bool = False) -> None:
            cls.rebuilt = force

    fake_models = SimpleNamespace(RequestHeaders=_Headers, RequestScopeInfo=_ScopeInfo)
    mocker.patch.object(_bootstrap, "import_module", return_value=fake_models)

    plugin._patch_filehost_request_headers_validator()

    assert hasattr(_Headers, "__htmlrender_validator_patched__")
    validate = _Headers.__dict__["validate"]
    assert isinstance(validate, classmethod)
    assert validate.__func__(_Headers, "x", "extra") == {"value": "x"}
    assert _ScopeInfo.rebuilt is True


def test_plugin_import_bootstraps_filehost_guard_for_playwright_backend(
    mocker: MockerFixture,
) -> None:
    filehost_runtime = import_module(
        "nonebot_plugin_htmlrender.resources.filehost"
    )

    guard = mocker.patch.object(
        filehost_runtime, "ensure_filehost_request_guard_installed", return_value=True
    )
    mocker.patch.object(
        _bootstrap,
        "plugin_config",
        mocker.Mock(render_backend=RenderBackend.PLAYWRIGHT),
    )

    plugin._bootstrap_filehost_guard_on_import()

    guard.assert_called_once_with(reason="plugin_import")


def test_plugin_import_skips_filehost_guard_for_non_playwright_backend(
    mocker: MockerFixture,
) -> None:
    import_module = mocker.patch.object(_bootstrap, "import_module")
    mocker.patch.object(
        _bootstrap, "plugin_config", mocker.Mock(render_backend=RenderBackend.SKIA)
    )

    plugin._bootstrap_filehost_guard_on_import()

    import_module.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("wrapper_name", "modern_name"),
    [
        ("text_to_pic", "render_text"),
        ("md_to_pic", "render_markdown"),
        ("template_to_html", "render_template_html"),
        ("html_to_pic", "render_html"),
        ("template_to_pic", "render_template"),
        ("capture_element", "capture_html_element"),
    ],
)
async def test_deprecated_wrappers_delegate_to_compat_apis(
    mocker: MockerFixture,
    wrapper_name: str,
    modern_name: str,
) -> None:
    """Deprecated wrappers exposed on the plugin module delegate to modern render APIs."""
    from nonebot_plugin_htmlrender import _compat  # noqa: PLC0415

    delegated = mocker.AsyncMock(return_value=b"ok")
    mocker.patch.object(_compat, modern_name, new=delegated)

    # Call the wrapper with minimal positional args (signature varies per function).
    wrapper = getattr(plugin, wrapper_name)
    if wrapper_name == "template_to_html":
        await wrapper("tpl_path", "tpl_name")
    elif wrapper_name == "template_to_pic":
        await wrapper("tpl_path", "tpl_name", {})
    elif wrapper_name == "capture_element":
        await wrapper("https://example.com", "#el")
    else:
        await wrapper("arg")

    delegated.assert_awaited_once()


@pytest.mark.anyio
async def test_startup_htmlrender_delegates_to_modern_api(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender import _compat  # noqa: PLC0415

    delegated = mocker.AsyncMock(return_value=SimpleNamespace(handle=object()))
    mocker.patch.object(_compat, "startup_render", new=delegated)
    mocker.patch.object(_compat, "_require_browser", return_value=mocker.MagicMock())

    await plugin.startup_htmlrender(slow_mo=1.0)

    delegated.assert_awaited_once_with(slow_mo=1.0)


@pytest.mark.anyio
async def test_shutdown_htmlrender_delegates_to_shutdown_render(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender import _compat  # noqa: PLC0415

    shutdown = mocker.patch.object(_compat, "shutdown_render", new=mocker.AsyncMock())

    await plugin.shutdown_htmlrender()

    shutdown.assert_awaited_once_with()


def test_compat_runtime_cleanups_import_runtime_on_call(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender import _compat  # noqa: PLC0415

    fake_runtime = ModuleType("nonebot_plugin_htmlrender.backend.playwright.runtime")
    clean_cache = mocker.Mock()
    reconcile_cache = mocker.Mock()
    fake_runtime.__dict__["clean_playwright_cache"] = clean_cache
    fake_runtime.__dict__["reconcile_legacy_playwright_cache"] = reconcile_cache
    mocker.patch.dict(
        sys.modules,
        {"nonebot_plugin_htmlrender.backend.playwright.runtime": fake_runtime},
    )

    _compat.clean_playwright_cache(cleanup=True)
    _compat.reconcile_legacy_playwright_cache(cleanup=False)

    clean_cache.assert_called_once_with(cleanup=True)
    reconcile_cache.assert_called_once_with(cleanup=False)


@pytest.mark.anyio
async def test_plugin_init_skips_when_backend_is_none(mocker: MockerFixture) -> None:
    startup = mocker.patch.object(plugin, "startup_render", new=mocker.AsyncMock())
    prepare_playwright = mocker.patch.object(plugin, "_prepare_playwright_startup")
    logger_info = mocker.patch.object(plugin.logger, "info")
    mocker.patch.object(plugin.plugin_config, "render_backend", None)
    mocker.patch.object(
        plugin.plugin_config, "render_startup_mode", new=RenderStartupMode.OFF
    )

    init_func = plugin.init
    init_kwargs: dict[str, object] = {"sample": "value"}
    await init_func(**init_kwargs)

    prepare_playwright.assert_not_called()
    startup.assert_not_awaited()
    assert any(
        "No render backend selected; startup skipped." in call.args[0]
        for call in logger_info.call_args_list
    )


@pytest.mark.anyio
async def test_plugin_init_skips_runtime_when_mode_is_off(
    mocker: MockerFixture,
) -> None:
    startup = mocker.patch.object(plugin, "startup_render", new=mocker.AsyncMock())
    prepare_playwright = mocker.patch.object(plugin, "_prepare_playwright_startup")
    probe = mocker.patch.object(plugin, "probe_render", new=mocker.AsyncMock())
    logger_info = mocker.patch.object(plugin.logger, "info")
    mocker.patch.object(
        plugin.plugin_config, "render_backend", RenderBackend.PLAYWRIGHT
    )
    mocker.patch.object(
        plugin.plugin_config, "render_startup_mode", new=RenderStartupMode.OFF
    )

    init_kwargs: dict[str, object] = {"slow_mo": 1.0}
    await plugin.init(**init_kwargs)

    prepare_playwright.assert_not_called()
    startup.assert_not_awaited()
    probe.assert_not_awaited()
    assert any(
        "Render startup skipped by configuration." in call.args[0]
        for call in logger_info.call_args_list
    )


@pytest.mark.anyio
async def test_plugin_init_warms_runtime_without_probe(
    mocker: MockerFixture,
) -> None:
    startup = mocker.patch.object(plugin, "startup_render", new=mocker.AsyncMock())
    prepare_playwright = mocker.patch.object(plugin, "_prepare_playwright_startup")
    probe = mocker.patch.object(plugin, "probe_render", new=mocker.AsyncMock())
    logger_opt = mocker.patch.object(plugin.logger, "opt")
    mocker.patch.object(plugin.plugin_config, "render_backend", RenderBackend.SKIA)
    mocker.patch.object(
        plugin.plugin_config, "render_startup_mode", new=RenderStartupMode.WARMUP
    )

    init_func = plugin.init
    init_kwargs: dict[str, object] = {"slow_mo": 1.0}
    await init_func(**init_kwargs)

    prepare_playwright.assert_not_called()
    startup.assert_awaited_once_with(slow_mo=1.0)
    probe.assert_not_awaited()
    logger_opt.assert_called_once_with(colors=True)
    logger_opt.return_value.info.assert_called_once()


@pytest.mark.anyio
async def test_plugin_init_probes_runtime_when_mode_is_probe(
    mocker: MockerFixture,
) -> None:
    filehost_runtime = import_module(
        "nonebot_plugin_htmlrender.resources.filehost"
    )

    startup = mocker.patch.object(plugin, "startup_render", new=mocker.AsyncMock())
    ensure_ready = mocker.patch.object(
        filehost_runtime, "ensure_filehost_runtime_ready", new=mocker.AsyncMock()
    )
    prepare_playwright = mocker.patch.object(plugin, "_prepare_playwright_startup")
    probe = mocker.patch.object(plugin, "probe_render", new=mocker.AsyncMock())
    mocker.patch.object(
        plugin.plugin_config, "render_backend", RenderBackend.PLAYWRIGHT
    )
    mocker.patch.object(
        plugin.plugin_config, "render_startup_mode", new=RenderStartupMode.PROBE
    )

    init_kwargs: dict[str, object] = {"timeout": 123.0}
    await plugin.init(**init_kwargs)

    prepare_playwright.assert_called_once_with()
    ensure_ready.assert_awaited_once_with(reason="plugin_startup")
    startup.assert_awaited_once_with(timeout=123.0)
    probe.assert_awaited_once_with()


@pytest.mark.anyio
async def test_plugin_init_raises_runtime_error_when_startup_fails(
    mocker: MockerFixture,
) -> None:
    startup = mocker.patch.object(plugin, "startup_render", new=mocker.AsyncMock())
    startup.side_effect = ValueError("boom")
    logger_exception = mocker.patch.object(plugin.logger, "exception")
    mocker.patch.object(plugin.plugin_config, "render_backend", RenderBackend.SKIA)
    mocker.patch.object(
        plugin.plugin_config, "render_startup_mode", new=RenderStartupMode.WARMUP
    )

    with pytest.raises(
        RuntimeError, match=r"Render runtime startup failed\."
    ) as exc_info:
        await plugin.init()

    logger_exception.assert_called_once_with("Failed to start render runtime.")
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.anyio
async def test_plugin_shutdown_calls_runtime_and_env_cleanup(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import runtime  # noqa: PLC0415

    shutdown = mocker.patch.object(plugin, "shutdown_render", new=mocker.AsyncMock())
    clear_env = mocker.patch.object(runtime, "clear_playwright_env_vars")
    logger_info = mocker.patch.object(plugin.logger, "info")
    mocker.patch.object(
        plugin.plugin_config, "render_backend", RenderBackend.PLAYWRIGHT
    )

    await plugin.shutdown()

    shutdown.assert_awaited_once_with()
    clear_env.assert_called_once_with()
    assert any(
        "HTMLRender Shutting down..." in call.args[0]
        for call in logger_info.call_args_list
    )
    assert any(
        "HTMLRender Shut down." in call.args[0] for call in logger_info.call_args_list
    )
