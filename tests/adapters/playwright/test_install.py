from contextlib import asynccontextmanager
import os
import sys

import pytest
from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_backend_download_context_sets_proxy_and_restores_host(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        download_context,
    )
    from nonebot_plugin_htmlrender.consts import MirrorSource  # noqa: PLC0415

    os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] = "https://old-host"
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.get_playwright_config",
        return_value=PlaywrightConfig(
            install_proxy="http://127.0.0.1:7890",
            install_mirror="https://mirror.example",
        ),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.check_mirror_connectivity",
        new=mocker.AsyncMock(
            return_value=MirrorSource("Best", "https://mirror.example", 0)
        ),
    )

    async with download_context():
        assert os.environ["PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT"] == "300000"
        assert os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] == "https://mirror.example"
        assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"

    assert os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] == "https://old-host"
    assert "HTTP_PROXY" not in os.environ

    del os.environ["PLAYWRIGHT_DOWNLOAD_HOST"]


@pytest.mark.anyio
async def test_execute_playwright_install_uses_direct_stdio(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        execute_install_command,
    )
    from nonebot_plugin_htmlrender.consts import BrowserEngine  # noqa: PLC0415

    execute_mock = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install._execute_install_command",
        new=mocker.AsyncMock(return_value=(True, "ok")),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.get_playwright_config",
        return_value=PlaywrightConfig(engine=BrowserEngine.FIREFOX),
    )
    result = await execute_install_command(9)

    assert result == (True, "ok")
    assert execute_mock.await_args is not None
    assert execute_mock.await_args.args[0] == (
        sys.executable,
        "-m",
        "playwright",
        "install",
        "--with-deps",
        BrowserEngine.FIREFOX,
    )
    assert execute_mock.await_args.kwargs["timeout_seconds"] == 9
    assert "stdout_callback" not in execute_mock.await_args.kwargs
    assert "stderr_callback" not in execute_mock.await_args.kwargs


@pytest.mark.anyio
async def test_install_browser_retries_without_mirror_host(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        install_browser,
    )

    seen_hosts: list[str | None] = []
    responses = iter([(False, "mirror failed"), (True, "ok")])

    @asynccontextmanager
    async def fake_download_context():
        os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] = "https://mirror.example"
        try:
            yield
        finally:
            os.environ.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)

    async def fake_execute(timeout_seconds: int) -> tuple[bool, str]:
        assert timeout_seconds == 7
        seen_hosts.append(os.environ.get("PLAYWRIGHT_DOWNLOAD_HOST"))
        return next(responses)

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.download_context",
        fake_download_context,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.get_playwright_config",
        return_value=PlaywrightConfig(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.execute_install_command",
        new=mocker.AsyncMock(side_effect=fake_execute),
    )

    result = await install_browser(timeout_seconds=7)

    assert result is True
    assert seen_hosts == ["https://mirror.example", None]


@pytest.mark.anyio
async def test_install_browser_returns_false_after_two_failures(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        install_browser,
    )

    @asynccontextmanager
    async def fake_download_context():
        yield

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.download_context",
        fake_download_context,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.get_playwright_config",
        return_value=PlaywrightConfig(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.execute_install_command",
        new=mocker.AsyncMock(side_effect=[(False, "first"), (False, "second")]),
    )

    assert await install_browser(timeout_seconds=3) is False


@pytest.mark.anyio
async def test_install_browser_raises_on_interrupt_without_retry(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        install_browser,
    )

    @asynccontextmanager
    async def fake_download_context():
        yield

    execute = mocker.AsyncMock(side_effect=[(False, "Interrupted by signal SIGINT")])
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.download_context",
        fake_download_context,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.get_playwright_config",
        return_value=PlaywrightConfig(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.execute_install_command",
        new=execute,
    )

    with pytest.raises(KeyboardInterrupt):
        await install_browser(timeout_seconds=3)
    assert execute.await_count == 1
