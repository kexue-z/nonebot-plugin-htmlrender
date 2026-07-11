from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.consts import BrowserEngine

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_runtime_storage_and_legacy_path_helpers(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import runtime  # noqa: PLC0415
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
        register_playwright_config_provider,
    )

    configured = PlaywrightConfig.model_validate({"storage_path": "~/pw-cache"})
    previous = register_playwright_config_provider(lambda: configured)
    try:
        storage = runtime.get_playwright_storage_path()
        assert isinstance(storage, Path)
        assert storage == Path("~/pw-cache").expanduser()
    finally:
        register_playwright_config_provider(previous)

    default_storage = runtime.get_playwright_storage_path()
    assert isinstance(default_storage, Path)

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.platform.system",
        return_value="Other",
    )
    assert runtime.get_legacy_playwright_cache_path() is None


def test_has_installed_browser_candidates(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import runtime  # noqa: PLC0415

    storage = tmp_path / "storage"
    storage.mkdir()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (storage / "chromium-1234").mkdir()
    (storage / "chromium_headless_shell-1234").mkdir()
    (legacy / "firefox-999").mkdir()

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_playwright_storage_path",
        return_value=storage,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_legacy_playwright_cache_path",
        return_value=legacy,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime._expected_browser_directory_groups",
        side_effect=lambda engine: {
            BrowserEngine.CHROMIUM: (
                ("chromium-1234",),
                ("chromium_headless_shell-1234",),
            ),
            BrowserEngine.FIREFOX: (("firefox-999",),),
            BrowserEngine.WEBKIT: (("webkit-777",),),
        }[engine],
    )

    assert runtime.has_installed_browser(BrowserEngine.CHROMIUM) is True
    assert runtime.has_installed_browser(BrowserEngine.FIREFOX) is True
    assert runtime.has_installed_browser(BrowserEngine.WEBKIT) is False


def test_has_installed_browser_rejects_stale_revision(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import runtime  # noqa: PLC0415

    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "chromium-older").mkdir()
    (storage / "chromium_headless_shell-older").mkdir()

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_playwright_storage_path",
        return_value=storage,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_legacy_playwright_cache_path",
        return_value=None,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime._expected_browser_directory_groups",
        return_value=(("chromium-new",), ("chromium_headless_shell-new",)),
    )

    assert runtime.has_installed_browser(BrowserEngine.CHROMIUM) is False


def test_expected_browser_directory_groups_reads_current_playwright_metadata(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import runtime  # noqa: PLC0415

    browsers_json = tmp_path / "browsers.json"
    browsers_json.write_text(
        """
        {
          "browsers": [
            {"name": "chromium", "revision": "111"},
            {"name": "chromium-headless-shell", "revision": "111"},
            {"name": "webkit", "revision": "222", "revisionOverrides": {"mac": "333"}}
          ]
        }
        """,
        encoding="utf-8",
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime._playwright_browsers_json_path",
        return_value=browsers_json,
    )

    assert runtime._expected_browser_directory_groups(BrowserEngine.CHROMIUM) == (
        ("chromium-111",),
        ("chromium_headless_shell-111",),
    )
    assert runtime._expected_browser_directory_groups(BrowserEngine.WEBKIT) == (
        ("webkit-222", "webkit-333"),
    )


def test_record_playwright_runtime_state_warns_on_version_change(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    import json  # noqa: PLC0415

    from nonebot_plugin_htmlrender.adapters.playwright import runtime  # noqa: PLC0415

    state_path = tmp_path / "playwright-runtime.json"
    state_path.write_text(
        json.dumps(
            {
                "2026-01-01T00:00:00+00:00": {
                    "venv": {
                        "prefix": "/old/venv",
                        "executable": "/old/venv/bin/python",
                    },
                    "playwright_version": "1.0.0",
                    "engines": {
                        "chromium": {
                            "browser_versions": {
                                "chromium": {
                                    "revision": "old",
                                    "browser_version": "old",
                                }
                            }
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime._runtime_state_path",
        return_value=state_path,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.build_playwright_runtime_snapshot",
        return_value={
            "venv": {"prefix": "/new/venv", "executable": "/new/venv/bin/python"},
            "playwright_version": "2.0.0",
            "browsers_json": str(tmp_path / "browsers.json"),
            "engines": {
                "chromium": {
                    "available": False,
                    "expected_directory_groups": [["chromium-new"]],
                    "browser_versions": {
                        "chromium": {
                            "revision": "new",
                            "browser_version": "new",
                        }
                    },
                    "paths": [],
                },
                "firefox": {"available": True, "browser_versions": {}, "paths": []},
                "webkit": {"available": True, "browser_versions": {}, "paths": []},
            },
        },
    )
    warning = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.logger.warning"
    )

    runtime.record_playwright_runtime_state()

    warning.assert_any_call(
        "Playwright package version changed since last htmlrender startup: "
        "1.0.0 -> 2.0.0. Browser cache compatibility will be rechecked."
    )
    written = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(written) == 2
    latest_key = max(written.keys())
    assert written[latest_key]["playwright_version"] == "2.0.0"
    assert "2026-01-01T00:00:00+00:00" in written


def test_record_playwright_runtime_state_evicts_oldest_entries(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    import json  # noqa: PLC0415

    from nonebot_plugin_htmlrender.adapters.playwright import runtime  # noqa: PLC0415

    history: dict[str, dict[str, object]] = {
        f"2026-01-{i:02d}T00:00:00+00:00": {
            "venv": {"prefix": f"/venv{i}", "executable": f"/venv{i}/bin/python"},
            "playwright_version": "1.0.0",
            "engines": {},
        }
        for i in range(1, 21)
    }
    state_path = tmp_path / "playwright-runtime.json"
    state_path.write_text(json.dumps(history), encoding="utf-8")

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime._runtime_state_path",
        return_value=state_path,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.build_playwright_runtime_snapshot",
        return_value={
            "venv": {"prefix": "/new", "executable": "/new/bin/python"},
            "playwright_version": "1.0.0",
            "engines": {},
        },
    )
    mocker.patch("nonebot_plugin_htmlrender.adapters.playwright.runtime.logger.warning")

    runtime.record_playwright_runtime_state()

    written = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(written) == 20
    assert "2026-01-01T00:00:00+00:00" not in written


def test_reconcile_legacy_playwright_cache_warns_without_deleting_by_default(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import runtime  # noqa: PLC0415

    storage = tmp_path / "storage"
    legacy = tmp_path / "legacy"
    storage.mkdir()
    legacy.mkdir()

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_playwright_storage_path",
        return_value=storage,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_legacy_playwright_cache_path",
        return_value=legacy,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_playwright_config",
        return_value=type("Cfg", (), {"cleanup_legacy_cache": False})(),
    )
    logger_warning = mocker.patch.object(runtime.logger, "warning")
    rmtree = mocker.patch.object(runtime.shutil, "rmtree")

    runtime.reconcile_legacy_playwright_cache(cleanup=False)

    logger_warning.assert_called_once()
    rmtree.assert_not_called()
    assert legacy.exists()


def test_reconcile_legacy_playwright_cache_deletes_legacy_cache_when_enabled(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import runtime  # noqa: PLC0415

    storage = tmp_path / "storage"
    legacy = tmp_path / "legacy"
    storage.mkdir()
    legacy.mkdir()

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_playwright_storage_path",
        return_value=storage,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_legacy_playwright_cache_path",
        return_value=legacy,
    )
    rmtree = mocker.patch.object(runtime.shutil, "rmtree")

    runtime.reconcile_legacy_playwright_cache(cleanup=True)

    rmtree.assert_called_once_with(str(legacy.resolve()))


def test_reconcile_legacy_playwright_cache_skips_when_storage_equals_legacy(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import runtime  # noqa: PLC0415

    shared = tmp_path / "shared"
    shared.mkdir()

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_playwright_storage_path",
        return_value=shared,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.runtime.get_legacy_playwright_cache_path",
        return_value=shared,
    )
    logger_warning = mocker.patch.object(runtime.logger, "warning")
    rmtree = mocker.patch.object(runtime.shutil, "rmtree")

    runtime.reconcile_legacy_playwright_cache(cleanup=True)

    logger_warning.assert_not_called()
    rmtree.assert_not_called()


def test_startup_steps_record_runtime_state() -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.render import (  # noqa: PLC0415
        PlaywrightBackend,
    )

    step_names = [step.__name__ for step in PlaywrightBackend().startup_steps()]  # ty: ignore[unresolved-attribute]
    assert "_record_runtime_state" in step_names
