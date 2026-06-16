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


def test_default_plugin_import_does_not_load_playwright_or_filehost() -> None:
    result = _run_python(
        """
        import importlib.abc
        import sys

        import nonebot

        nonebot.init(log_level="ERROR", render_backend=None, render_startup_mode="off")

        class _BlockFastAPI(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                del path, target
                if fullname == "fastapi" or fullname.startswith("fastapi."):
                    raise ModuleNotFoundError(fullname)
                return None

        sys.meta_path.insert(0, _BlockFastAPI())
        nonebot.require("nonebot_plugin_htmlrender")

        unexpected = {
            "nonebot_plugin_htmlrender.backend.playwright.render",
            "nonebot_plugin_htmlrender.resources.filehost",
            "nonebot_plugin_htmlrender.resources.filehost.guard",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected lazy modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_playwright_import_without_filehost_policy_does_not_load_filehost() -> None:
    result = _run_python(
        """
        import importlib.abc
        import sys

        import nonebot

        nonebot.init(
            log_level="ERROR",
            render_backend="playwright",
            render_startup_mode="off",
            render_playwright={
                "resource_resolve_mode": "auto",
                "remote_local_resource_policy": "passthrough",
                "local_local_resource_policy": "file",
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
            "nonebot_plugin_filehost",
            "nonebot_plugin_htmlrender.backend.playwright.render",
            "nonebot_plugin_htmlrender.resources.filehost",
            "nonebot_plugin_htmlrender.resources.filehost.guard",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected lazy modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_playwright_import_with_filehost_policy_loads_filehost_before_startup() -> None:
    result = _run_python(
        """
        import sys

        import nonebot

        nonebot.init(
            driver="~fastapi",
            log_level="ERROR",
            render_backend="playwright",
            render_startup_mode="off",
            render_playwright={
                "resource_resolve_mode": "auto",
                "remote_local_resource_policy": "filehost",
                "local_local_resource_policy": "file",
            },
        )
        nonebot.require("nonebot_plugin_htmlrender")

        missing = {
            "nonebot_plugin_filehost",
            "nonebot_plugin_htmlrender.resources.filehost",
            "nonebot_plugin_htmlrender.resources.filehost.guard",
        } - set(sys.modules)
        if missing:
            raise SystemExit(f"expected filehost modules were not loaded: {sorted(missing)}")

        unexpected = {
            "nonebot_plugin_htmlrender.backend.playwright.render",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected backend modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_compat_import_paths_do_not_load_playwright() -> None:
    result = _run_python(
        """
        import sys

        import nonebot

        nonebot.init(log_level="ERROR", render_backend=None, render_startup_mode="off")
        nonebot.require("nonebot_plugin_htmlrender")

        import nonebot_plugin_htmlrender._compat
        import nonebot_plugin_htmlrender.browser
        import nonebot_plugin_htmlrender.data_source

        unexpected = {
            "nonebot_plugin_htmlrender.backend.playwright.operations",
            "nonebot_plugin_htmlrender.backend.playwright.render",
            "nonebot_plugin_htmlrender.backend.playwright.runtime",
            "playwright.async_api",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected lazy modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr


def test_backend_packages_do_not_use_module_getattr_facades() -> None:
    result = _run_python(
        """
        import sys

        import nonebot

        nonebot.init(log_level="ERROR", render_backend=None, render_startup_mode="off")
        nonebot.require("nonebot_plugin_htmlrender")

        import nonebot_plugin_htmlrender.backend as backend
        import nonebot_plugin_htmlrender.backend.playwright as playwright_pkg

        if "__getattr__" in backend.__dict__:
            raise SystemExit("backend package must not use module __getattr__")
        if "__getattr__" in playwright_pkg.__dict__:
            raise SystemExit("playwright package must not use module __getattr__")

        unexpected = {
            "nonebot_plugin_htmlrender.backend.playwright.render",
            "nonebot_plugin_htmlrender.resources.filehost",
            "nonebot_plugin_htmlrender.resources.filehost.guard",
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

        nonebot.init(log_level="ERROR", render_backend=None, render_startup_mode="off")
        nonebot.require("nonebot_plugin_htmlrender")

        from nonebot_plugin_htmlrender.backend.playwright import runtime

        if runtime.__name__ != "nonebot_plugin_htmlrender.backend.playwright.runtime":
            raise SystemExit("runtime submodule import resolved incorrectly")

        unexpected = {
            "nonebot_plugin_htmlrender.backend.playwright.render",
            "nonebot_plugin_htmlrender.resources.filehost",
            "nonebot_plugin_htmlrender.resources.filehost.guard",
        } & set(sys.modules)
        if unexpected:
            raise SystemExit(f"unexpected lazy modules loaded: {sorted(unexpected)}")
        """
    )

    assert result.returncode == 0, result.stderr
