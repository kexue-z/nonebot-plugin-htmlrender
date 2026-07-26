from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_install_env_sets_mirror_proxy_without_mutating_parent(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        MirrorSource,
        _install_env,
    )

    mocker.patch.dict(os.environ, {}, clear=False)
    os.environ.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
    os.environ.pop("HTTP_PROXY", None)
    parent_before = dict(os.environ)

    config = PlaywrightConfig(
        install_proxy="http://127.0.0.1:7890",
        install_mirror="https://mirror.example",
    )
    mirror = MirrorSource("Best", "https://mirror.example", 0)

    selected = _install_env(config, mirror)
    official = _install_env(config, None)

    assert selected["PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT"] == "300000"
    assert selected["PLAYWRIGHT_DOWNLOAD_HOST"] == "https://mirror.example"
    assert selected["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert "PLAYWRIGHT_DOWNLOAD_HOST" not in official
    assert official["HTTP_PROXY"] == "http://127.0.0.1:7890"
    # Parent process environment must remain byte-for-byte unchanged.
    assert dict(os.environ) == parent_before


@pytest.mark.anyio
async def test_install_env_preserves_existing_parent_proxy(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        _install_env,
    )

    mocker.patch.dict(os.environ, {"HTTP_PROXY": "http://parent-proxy"}, clear=False)
    config = PlaywrightConfig(install_proxy="http://127.0.0.1:7890")

    env = _install_env(config, None)

    assert env["HTTP_PROXY"] == "http://parent-proxy"


@pytest.mark.anyio
async def test_check_mirror_connectivity_includes_custom_mirror(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import install  # noqa: PLC0415
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )

    checker = mocker.patch.object(
        install,
        "_check_mirror_connectivity",
        new=mocker.AsyncMock(return_value=None),
    )

    await install.check_mirror_connectivity(
        PlaywrightConfig(install_mirror="https://custom.mirror"),
        timeout_seconds=2,
    )

    assert checker.await_args is not None
    mirrors = checker.await_args.args[0]
    assert any(mirror.url == "https://custom.mirror" for mirror in mirrors)
    assert checker.await_args.kwargs["timeout_seconds"] == 2


@pytest.mark.anyio
async def test_execute_playwright_install_forwards_env_and_command(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        BrowserEngine,
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        execute_install_command,
    )

    execute_mock = mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install._execute_install_command",
        new=mocker.AsyncMock(return_value=(True, "ok")),
    )
    config = PlaywrightConfig(engine=BrowserEngine.FIREFOX)
    env = {"PLAYWRIGHT_DOWNLOAD_HOST": "https://mirror.example"}
    result = await execute_install_command(config, 9, env=env)

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
    assert execute_mock.await_args.kwargs["env"] is env


@pytest.mark.anyio
async def test_install_browser_retries_with_official_env(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        MirrorSource,
        install_browser,
    )

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.check_mirror_connectivity",
        new=mocker.AsyncMock(
            return_value=MirrorSource("Best", "https://mirror.example", 0)
        ),
    )
    seen_hosts: list[str | None] = []
    responses = iter([(False, "mirror failed"), (True, "ok")])

    async def fake_execute(
        config: PlaywrightConfig,
        timeout_seconds: int,
        *,
        env: dict[str, str],
    ) -> tuple[bool, str]:
        del config
        assert timeout_seconds == 7
        seen_hosts.append(env.get("PLAYWRIGHT_DOWNLOAD_HOST"))
        return next(responses)

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.execute_install_command",
        new=mocker.AsyncMock(side_effect=fake_execute),
    )

    result = await install_browser(PlaywrightConfig(), timeout_seconds=7)

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

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.check_mirror_connectivity",
        new=mocker.AsyncMock(return_value=None),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.execute_install_command",
        new=mocker.AsyncMock(side_effect=[(False, "first"), (False, "second")]),
    )

    assert await install_browser(PlaywrightConfig(), timeout_seconds=3) is False


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

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.check_mirror_connectivity",
        new=mocker.AsyncMock(return_value=None),
    )
    execute = mocker.AsyncMock(side_effect=[(False, "Interrupted by signal SIGINT")])
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.install.execute_install_command",
        new=execute,
    )

    with pytest.raises(KeyboardInterrupt):
        await install_browser(PlaywrightConfig(), timeout_seconds=3)
    assert execute.await_count == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "https://user:pass@example.com:8443/path?q=1#x",
            "https://example.com:8443/path",
        ),
        (
            "http://token:secret@127.0.0.1:8080/install?abc=1",
            "http://127.0.0.1:8080/install",
        ),
    ],
)
def test_redact_url_removes_sensitive_components(value: str, expected: str) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright.install import (  # noqa: PLC0415
        _redact_url,
    )

    assert _redact_url(value) == expected
