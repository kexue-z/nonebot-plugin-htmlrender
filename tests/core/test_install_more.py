from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.consts import MirrorSource

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_install_check_mirror_connectivity_appends_custom_mirror(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import install  # noqa: PLC0415

    mocker.patch.object(
        install,
        "get_playwright_config",
        return_value=SimpleNamespace(install_mirror="https://custom.mirror"),
    )
    checker = mocker.patch.object(
        install,
        "_check_mirror_connectivity",
        new=mocker.AsyncMock(return_value=None),
    )

    await install.check_mirror_connectivity(timeout_seconds=2)

    assert checker.await_args is not None
    called_mirrors = checker.await_args.args[0]
    assert any(item.url == "https://custom.mirror" for item in called_mirrors)
    assert checker.await_args.kwargs["timeout_seconds"] == 2


@pytest.mark.anyio
async def test_download_context_proxy_and_host_restore(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import install  # noqa: PLC0415

    mocker.patch.object(
        install,
        "get_playwright_config",
        return_value=SimpleNamespace(install_proxy="http://u:p@proxy.local:8080"),
    )
    mocker.patch.object(
        install,
        "check_mirror_connectivity",
        new=mocker.AsyncMock(
            return_value=MirrorSource("best", "https://best.mirror", 1)
        ),
    )
    mocker.patch.dict(
        "os.environ",
        {"PLAYWRIGHT_DOWNLOAD_HOST": "https://origin.mirror"},
        clear=False,
    )

    async with install.download_context():
        assert install.os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] == "https://best.mirror"
        assert install.os.environ["HTTP_PROXY"] == "http://u:p@proxy.local:8080"

    assert install.os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] == "https://origin.mirror"
    assert "HTTP_PROXY" not in install.os.environ


@pytest.mark.anyio
async def test_execute_install_command_uses_direct_stdio(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import install  # noqa: PLC0415

    helper = mocker.patch.object(
        install,
        "_execute_install_command",
        new=mocker.AsyncMock(return_value=(True, "ok")),
    )

    ok, _ = await install.execute_install_command(timeout_seconds=5)
    assert ok is True

    assert helper.await_args is not None
    kwargs = helper.await_args.kwargs
    assert "stdout_callback" not in kwargs
    assert "stderr_callback" not in kwargs


@pytest.mark.anyio
async def test_install_browser_retry_paths(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import install  # noqa: PLC0415

    @asynccontextmanager
    async def _ctx():
        yield

    mocker.patch.object(install, "download_context", _ctx)
    mocker.patch.object(
        install,
        "get_playwright_config",
        return_value=SimpleNamespace(engine="chromium"),
    )

    first_try = mocker.patch.object(
        install,
        "execute_install_command",
        new=mocker.AsyncMock(side_effect=[(True, "ok")]),
    )
    assert await install.install_browser(timeout_seconds=3) is True
    first_try.assert_awaited_once_with(3)

    second_try = mocker.patch.object(
        install,
        "execute_install_command",
        new=mocker.AsyncMock(side_effect=[(False, "x"), (True, "ok")]),
    )
    assert await install.install_browser(timeout_seconds=3) is True
    assert second_try.await_count == 2

    third_try = mocker.patch.object(
        install,
        "execute_install_command",
        new=mocker.AsyncMock(side_effect=[(False, "x"), (False, "final")]),
    )
    assert await install.install_browser(timeout_seconds=3) is False
    assert third_try.await_count == 2

    interrupted = mocker.patch.object(
        install,
        "execute_install_command",
        new=mocker.AsyncMock(side_effect=[(False, "Interrupted by signal SIGINT")]),
    )
    with pytest.raises(KeyboardInterrupt):
        await install.install_browser(timeout_seconds=3)
    assert interrupted.await_count == 1
