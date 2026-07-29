from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_default_plugin_import_does_not_load_engines_or_filehost() -> None:
    result = _run_python(
        """
        import importlib.abc
        import sys

        import nonebot

        nonebot.init(log_level="ERROR", render={"provider": None})

        class _BlockFastAPI(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                del path, target
                if fullname == "fastapi" or fullname.startswith("fastapi."):
                    raise ModuleNotFoundError(fullname)
                return None

        sys.meta_path.insert(0, _BlockFastAPI())
        nonebot.require("nonebot_plugin_htmlrender")

        unexpected = {
            "PIL",
            "nonebot_plugin_htmlkit",
            "playwright.async_api",
            "skia",
            "takumi_py",
            "nonebot_plugin_htmlrender.adapters.htmlkit.provider",
            "nonebot_plugin_htmlrender.adapters.pillow.renderer",
            "nonebot_plugin_htmlrender.adapters.playwright.render",
            "nonebot_plugin_htmlrender.adapters.skia.renderer",
            "nonebot_plugin_htmlrender.adapters.takumi.provider",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected lazy modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_playwright_provider_off_startup_stays_lazy() -> None:
    result = _run_python(
        """
        import importlib.abc
        import sys

        import nonebot

        nonebot.init(
            log_level="ERROR",
            render={
                "provider": "playwright",
                "startup": "off",
                "provider_config": {
                    "resource_resolve_mode": "auto",
                    "remote_local_resource_policy": "passthrough",
                    "local_local_resource_policy": "file",
                },
            },
        )

        class _BlockFastAPI(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                del path, target
                if fullname == "fastapi" or fullname.startswith("fastapi."):
                    raise ModuleNotFoundError(fullname)
                return None

        sys.meta_path.insert(0, _BlockFastAPI())
        nonebot.require("nonebot_plugin_htmlrender")

        unexpected = {
            "nonebot_plugin_htmlkit",
            "playwright.async_api",
            "nonebot_plugin_htmlrender.adapters.playwright.render",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected lazy modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_htmlkit_provider_bootstraps_only_its_required_plugin() -> None:
    result = _run_python(
        """
        import sys

        import nonebot

        nonebot.init(
            driver="~none",
            log_level="ERROR",
            render={"provider": "htmlkit", "startup": "off"},
        )
        nonebot.require("nonebot_plugin_htmlrender")

        if "nonebot_plugin_htmlkit" not in sys.modules:
            raise SystemExit("HTMLKit provider did not bootstrap its required plugin")

        unexpected = {
            "PIL",
            "playwright.async_api",
            "skia",
            "takumi_py",
            "nonebot_plugin_htmlrender.adapters.pillow.renderer",
            "nonebot_plugin_htmlrender.adapters.playwright.render",
            "nonebot_plugin_htmlrender.adapters.skia.renderer",
            "nonebot_plugin_htmlrender.adapters.takumi.provider",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected sibling backends loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_graphics_backend_composes_without_loading_html_engines() -> None:
    result = _run_python(
        """
        import sys

        import nonebot

        nonebot.init(
            log_level="ERROR",
            render={
                "provider": None,
                "graphics": {"backends": ["pillow"]},
            },
        )
        nonebot.require("nonebot_plugin_htmlrender")

        from nonebot_plugin_htmlrender import get_default_application

        get_default_application()
        if "nonebot_plugin_htmlrender.adapters.pillow.renderer" not in sys.modules:
            raise SystemExit("configured Pillow capability was not composed")

        unexpected = {
            "nonebot_plugin_htmlkit",
            "playwright.async_api",
            "takumi_py",
            "nonebot_plugin_htmlrender.adapters.htmlkit.provider",
            "nonebot_plugin_htmlrender.adapters.playwright.render",
            "nonebot_plugin_htmlrender.adapters.takumi.provider",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected HTML engines loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_missing_playwright_extra_keeps_preparation_available() -> None:
    result = _run_python(
        """
        import importlib.abc
        import sys

        import anyio
        import nonebot

        class _BlockPlaywright(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                del path, target
                if fullname == "playwright" or fullname.startswith("playwright."):
                    raise ModuleNotFoundError(fullname)
                return None

        sys.meta_path.insert(0, _BlockPlaywright())
        nonebot.init(
            log_level="ERROR",
            render={"provider": "playwright", "startup": "off"},
        )
        nonebot.require("nonebot_plugin_htmlrender")

        from nonebot_plugin_htmlrender import get_default_application

        application = get_default_application()

        async def check_preparation():
            prepared = await application.preparation.prepare_text("hello")
            if "hello" not in prepared.html:
                raise SystemExit("preparation did not produce text HTML")

        anyio.run(check_preparation)
        if "nonebot_plugin_htmlrender.adapters.playwright.render" in sys.modules:
            raise SystemExit("availability imported the heavy Playwright backend")
        """
    )

    assert result.returncode == 0, result.stderr


def test_filehost_policy_mounts_hosted_assets_before_startup() -> None:
    result = _run_python(
        """
        import sys

        import nonebot

        nonebot.init(
            driver="~fastapi",
            log_level="ERROR",
            render={
                "provider": "playwright",
                "startup": "off",
                "provider_config": {
                    "resource_resolve_mode": "auto",
                    "remote_local_resource_policy": "filehost",
                    "local_local_resource_policy": "filehost",
                },
                "resources": {
                    "filehost": {
                        "public_base_url": "http://assets.example/htmlrender/",
                    },
                },
            },
        )
        nonebot.require("nonebot_plugin_htmlrender")

        driver = nonebot.get_driver()
        paths = [route.path for route in driver.server_app.routes]
        if not any(path.startswith("/_htmlrender/assets/") for path in paths):
            raise SystemExit("hosted asset mount was not installed at import")

        unexpected = {
            "playwright.async_api",
            "nonebot_plugin_htmlrender.adapters.playwright.render",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected backend modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_legacy_configuration_keys_fail_plugin_load() -> None:
    result = _run_python(
        """
        import nonebot

        nonebot.init(
            log_level="ERROR",
            render_backend="playwright",
            render={"provider": None},
        )
        try:
            nonebot.require("nonebot_plugin_htmlrender")
        except RuntimeError:
            raise SystemExit(0)
        raise SystemExit("plugin load must fail on legacy render_backend key")
        """
    )

    assert result.returncode == 0, result.stderr


def test_playwright_adapter_package_is_static_and_lazy() -> None:
    result = _run_python(
        """
        import sys

        import nonebot

        nonebot.init(log_level="ERROR", render={"provider": None})
        nonebot.require("nonebot_plugin_htmlrender")

        import nonebot_plugin_htmlrender.adapters.playwright as playwright_pkg

        if "__getattr__" in playwright_pkg.__dict__:
            raise SystemExit("playwright package must not use module __getattr__")

        unexpected = {
            "nonebot_plugin_htmlrender.adapters.playwright.render",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected lazy modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_playwright_package_submodule_import_does_not_load_backend_render() -> None:
    result = _run_python(
        """
        import sys

        import nonebot

        nonebot.init(log_level="ERROR", render={"provider": None})
        nonebot.require("nonebot_plugin_htmlrender")

        from nonebot_plugin_htmlrender.adapters.playwright import install_state as runtime

        if runtime.__name__ != "nonebot_plugin_htmlrender.adapters.playwright.install_state":
            raise SystemExit("runtime submodule import resolved incorrectly")

        unexpected = {
            "nonebot_plugin_htmlrender.adapters.playwright.render",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected lazy modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr
