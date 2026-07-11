import os
from pathlib import Path
from typing import Any

import nonebot
import pytest

_TEST_PROFILE_ENV = "HTMLRENDER_TEST_PROFILE"
_TEST_ANYIO_BACKEND_ENV = "HTMLRENDER_TEST_ANYIO_BACKEND"
_LOCAL_TEST_PROFILE = "local"
_CI_TEST_PROFILE = "ci"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TEST_PLAYWRIGHT_BROWSERS_PATH = _PROJECT_ROOT / ".artifacts" / "playwright-browsers"
_PLAYWRIGHT_CHROMIUM_PATTERNS = ("chromium-*", "chromium_headless_shell-*")


def _get_test_profile() -> str:
    profile = os.environ.get(_TEST_PROFILE_ENV)
    if profile is not None:
        return profile.lower()

    if os.environ.get("CI", "").lower() in {"1", "true", "yes"}:
        return _CI_TEST_PROFILE
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        return _CI_TEST_PROFILE
    return _LOCAL_TEST_PROFILE


_TEST_PROFILE = _get_test_profile()


def _is_ci_test_profile() -> bool:
    return _TEST_PROFILE == _CI_TEST_PROFILE


def _has_test_browser_installation() -> bool:
    if not _TEST_PLAYWRIGHT_BROWSERS_PATH.exists():
        return False

    return any(
        path.is_dir()
        for pattern in _PLAYWRIGHT_CHROMIUM_PATTERNS
        for path in _TEST_PLAYWRIGHT_BROWSERS_PATH.glob(pattern)
    )


def _configure_playwright_test_env() -> None:
    os.environ.pop("PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT", None)
    os.environ.pop("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", None)

    if _is_ci_test_profile():
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        return

    _TEST_PLAYWRIGHT_BROWSERS_PATH.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_TEST_PLAYWRIGHT_BROWSERS_PATH)


def _build_test_init_kwargs() -> dict[str, Any]:
    provider_config: dict[str, Any] = {
        "engine": "chromium",
        "skip_browser_install": True,
    }
    if not _is_ci_test_profile():
        provider_config["storage_path"] = str(_TEST_PLAYWRIGHT_BROWSERS_PATH)

    return {
        "superusers": {"10001"},
        "command_start": {""},
        "log_level": "DEBUG",
        "render": {
            "provider": "playwright",
            "startup": "off",
            "provider_config": provider_config,
        },
    }


def pytest_configure(config: pytest.Config) -> None:
    _configure_playwright_test_env()
    try:
        nonebot.get_driver()
    except Exception:
        nonebot.init(**_build_test_init_kwargs())
    nonebot.require("nonebot_plugin_htmlrender")
    del config


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    del config
    if not _is_ci_test_profile():
        if _has_test_browser_installation():
            return

        skip_browser = pytest.mark.skip(
            reason=(
                "Real-browser tests require a project-local Playwright install. "
                "Run `make install-browser` first."
            )
        )
        for item in items:
            if "requires_browser" in item.keywords:
                item.add_marker(skip_browser)
        return

    skip_browser = pytest.mark.skip(
        reason="Real-browser tests are skipped in CI profile."
    )
    for item in items:
        if "requires_browser" in item.keywords:
            item.add_marker(skip_browser)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    backend = os.environ.get(_TEST_ANYIO_BACKEND_ENV, "asyncio").strip().lower()
    return backend or "asyncio"
