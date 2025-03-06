import asyncio
from collections.abc import AsyncGenerator
import os

import pytest
from pytest_mock import MockerFixture


@pytest.fixture
async def mock_stream() -> AsyncGenerator[asyncio.StreamReader, None]:
    """创建模拟的数据流"""
    stream = asyncio.StreamReader()
    stream.feed_data(b"test line\n")
    stream.feed_data(b"|#####     | 50% Progress\n")
    stream.feed_data(b"final line\n")
    stream.feed_eof()
    yield stream  # noqa: PT022


@pytest.mark.asyncio
async def test_check_mirror_connectivity(mocker: MockerFixture):
    # Mock socket connection
    from nonebot_plugin_htmlrender.consts import MirrorSource
    from nonebot_plugin_htmlrender.install import (
        check_mirror_connectivity,
    )

    mock_open_connection = mocker.patch("asyncio.open_connection")
    mock_open_connection.return_value = (None, None)

    result = await check_mirror_connectivity(timeout=1)
    assert isinstance(result, (MirrorSource, type(None)))


@pytest.mark.asyncio
async def test_download_context(mocker: MockerFixture):
    from nonebot_plugin_htmlrender.consts import MirrorSource
    from nonebot_plugin_htmlrender.install import (
        download_context,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.install.check_mirror_connectivity",
        return_value=MirrorSource("test", "http://test.com", 1),
    )

    async with download_context():
        assert "PLAYWRIGHT_DOWNLOAD_HOST" in os.environ

    assert "PLAYWRIGHT_DOWNLOAD_HOST" not in os.environ


@pytest.mark.asyncio
async def test_read_stream(mock_stream):
    from nonebot_plugin_htmlrender.install import (
        read_stream,
    )

    received_lines = []

    async def callback(line: str):
        received_lines.append(line)

    output = await read_stream(mock_stream, callback)

    assert "test line" in output
    assert any("50% Progress" in line for line in received_lines)
    assert "final line" in output


@pytest.mark.asyncio
async def test_execute_install_command(mocker: MockerFixture, mock_stream):
    # Mock process creation
    from nonebot_plugin_htmlrender.install import (
        execute_install_command,
    )

    mock_process = mocker.AsyncMock()
    mock_process.returncode = 0
    mock_process.stdout = mock_stream
    mock_process.stderr = mock_stream

    mocker.patch(
        "nonebot_plugin_htmlrender.install.create_process", return_value=mock_process
    )

    success, message = await execute_install_command(timeout=5)
    assert success
    assert "Installation completed" in message


@pytest.mark.asyncio
async def test_execute_install_command_timeout(mocker: MockerFixture, mock_stream):
    """测试安装超时场景"""
    from nonebot_plugin_htmlrender.install import execute_install_command

    mock_process = mocker.AsyncMock()
    mock_process.stdout = mock_stream
    mock_process.stderr = mock_stream
    mock_process.returncode = None
    mock_process.pid = 12345

    mock_terminate = mocker.patch(
        "nonebot_plugin_htmlrender.install.terminate_process", return_value=None
    )
    mocker.patch("asyncio.gather", side_effect=asyncio.TimeoutError())
    mocker.patch(
        "nonebot_plugin_htmlrender.install.create_process", return_value=mock_process
    )

    success, message = await execute_install_command(timeout=1)

    assert not success
    assert message == "Timed out (1s)"
    mock_terminate.assert_called_once_with(mock_process)


@pytest.mark.asyncio
async def test_install_browser(mocker: MockerFixture):
    # Mock execute_install_command
    from nonebot_plugin_htmlrender.install import (
        install_browser,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.install.execute_install_command",
        return_value=(True, "安装完成"),
    )

    result = await install_browser(timeout=5)
    assert result is True
