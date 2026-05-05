import os
import sys

import pytest
from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_check_mirror_connectivity(mocker: MockerFixture):
    # Mock socket connection
    from nonebot_plugin_htmlrender.backend.playwright.install import (  # noqa: PLC0415
        check_mirror_connectivity,
    )
    from nonebot_plugin_htmlrender.consts import MirrorSource  # noqa: PLC0415

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.install._check_mirror_connectivity",
        new=mocker.AsyncMock(return_value=None),
    )

    result = await check_mirror_connectivity(timeout_seconds=1)
    assert isinstance(result, (MirrorSource, type(None)))


@pytest.mark.anyio
async def test_download_context(mocker: MockerFixture):
    from nonebot_plugin_htmlrender.backend.playwright.install import (  # noqa: PLC0415
        download_context,
    )
    from nonebot_plugin_htmlrender.consts import MirrorSource  # noqa: PLC0415

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.install.check_mirror_connectivity",
        return_value=MirrorSource("test", "http://test.com", 1),
    )

    async with download_context():
        assert "PLAYWRIGHT_DOWNLOAD_HOST" in os.environ

    assert "PLAYWRIGHT_DOWNLOAD_HOST" not in os.environ


@pytest.mark.anyio
async def test_execute_install_command(mocker: MockerFixture):
    from nonebot_plugin_htmlrender.backend.playwright.install import (  # noqa: PLC0415
        execute_install_command,
    )

    execute_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.install._execute_install_command",
        new=mocker.AsyncMock(return_value=(True, "Installation completed")),
    )

    success, message = await execute_install_command(timeout_seconds=5)

    assert success
    assert "Installation completed" in message
    assert execute_mock.await_count == 1
    assert execute_mock.await_args is not None
    assert execute_mock.await_args.kwargs["timeout_seconds"] == 5
    command = execute_mock.await_args.args[0]
    assert command[:4] == (
        sys.executable,
        "-m",
        "playwright",
        "install",
    )


@pytest.mark.anyio
async def test_execute_install_command_timeout(mocker: MockerFixture):
    """测试安装超时场景"""
    from nonebot_plugin_htmlrender.backend.playwright.install import (  # noqa: PLC0415
        execute_install_command,
    )

    execute_mock = mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.install._execute_install_command",
        new=mocker.AsyncMock(return_value=(False, "Timed out (1s)")),
    )

    success, message = await execute_install_command(timeout_seconds=1)

    assert not success
    assert message == "Timed out (1s)"
    assert execute_mock.await_count == 1
    assert execute_mock.await_args is not None
    assert execute_mock.await_args.kwargs["timeout_seconds"] == 1


@pytest.mark.anyio
async def test_install_browser(mocker: MockerFixture):
    # Mock execute_install_command
    from nonebot_plugin_htmlrender.backend.playwright.install import (  # noqa: PLC0415
        install_browser,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.install.execute_install_command",
        new=mocker.AsyncMock(return_value=(True, "安装完成")),
    )

    result = await install_browser(timeout_seconds=5)
    assert result is True


def test_redact_url_masks_credentials_in_playwright_install_module() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.install import (  # noqa: PLC0415
        _redact_url,
    )

    assert (
        _redact_url("https://user:pass@example.com:8443/path?q=1#x")
        == "https://example.com:8443/path"
    )


def test_redact_url_masks_credentials_in_backend_install_module() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.install import (  # noqa: PLC0415
        _redact_url,
    )

    assert (
        _redact_url("http://token:secret@127.0.0.1:8080/install?abc=1")
        == "http://127.0.0.1:8080/install"
    )
