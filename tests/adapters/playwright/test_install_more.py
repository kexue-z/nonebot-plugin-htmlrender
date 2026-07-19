from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.adapters.playwright.config import PlaywrightConfig
from nonebot_plugin_htmlrender.adapters.playwright.install import MirrorSource

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_install_check_mirror_connectivity_appends_custom_mirror(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import install  # noqa: PLC0415

    config = PlaywrightConfig(install_mirror="https://custom.mirror")
    checker = mocker.patch.object(
        install,
        "_check_mirror_connectivity",
        new=mocker.AsyncMock(return_value=None),
    )

    await install.check_mirror_connectivity(config, timeout_seconds=2)

    assert checker.await_args is not None
    called_mirrors = checker.await_args.args[0]
    assert any(item.url == "https://custom.mirror" for item in called_mirrors)
    assert checker.await_args.kwargs["timeout_seconds"] == 2


@pytest.mark.anyio
async def test_install_env_selects_mirror_and_forwards_proxy(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import install  # noqa: PLC0415

    config = PlaywrightConfig(install_proxy="http://u:p@proxy.local:8080")
    mocker.patch.dict(
        "os.environ",
        {"PLAYWRIGHT_DOWNLOAD_HOST": "https://origin.mirror", "HTTP_PROXY": ""},
        clear=False,
    )
    del install.os.environ["HTTP_PROXY"]
    parent_before = dict(install.os.environ)

    selected = install._install_env(
        config, MirrorSource("best", "https://best.mirror", 1)
    )

    assert selected["PLAYWRIGHT_DOWNLOAD_HOST"] == "https://best.mirror"
    assert selected["HTTP_PROXY"] == "http://u:p@proxy.local:8080"
    # Parent environment (including its pre-existing DOWNLOAD_HOST) is untouched.
    assert dict(install.os.environ) == parent_before
    assert install.os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] == "https://origin.mirror"


@pytest.mark.anyio
async def test_execute_install_command_forwards_env_kwarg(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import install  # noqa: PLC0415

    helper = mocker.patch.object(
        install,
        "_execute_install_command",
        new=mocker.AsyncMock(return_value=(True, "ok")),
    )

    config = PlaywrightConfig()
    env = {"PLAYWRIGHT_DOWNLOAD_HOST": "https://best.mirror"}
    ok, _ = await install.execute_install_command(config, timeout_seconds=5, env=env)
    assert ok is True

    assert helper.await_args is not None
    assert helper.await_args.kwargs["env"] is env


@pytest.mark.anyio
async def test_install_browser_retry_paths(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender.adapters.playwright import install  # noqa: PLC0415

    config = PlaywrightConfig()
    mocker.patch.object(
        install,
        "check_mirror_connectivity",
        new=mocker.AsyncMock(return_value=None),
    )

    first_try = mocker.patch.object(
        install,
        "execute_install_command",
        new=mocker.AsyncMock(side_effect=[(True, "ok")]),
    )
    assert await install.install_browser(config, timeout_seconds=3) is True
    assert first_try.await_count == 1

    second_try = mocker.patch.object(
        install,
        "execute_install_command",
        new=mocker.AsyncMock(side_effect=[(False, "x"), (True, "ok")]),
    )
    assert await install.install_browser(config, timeout_seconds=3) is True
    assert second_try.await_count == 2

    third_try = mocker.patch.object(
        install,
        "execute_install_command",
        new=mocker.AsyncMock(side_effect=[(False, "x"), (False, "final")]),
    )
    assert await install.install_browser(config, timeout_seconds=3) is False
    assert third_try.await_count == 2

    interrupted = mocker.patch.object(
        install,
        "execute_install_command",
        new=mocker.AsyncMock(side_effect=[(False, "Interrupted by signal SIGINT")]),
    )
    with pytest.raises(KeyboardInterrupt):
        await install.install_browser(config, timeout_seconds=3)
    assert interrupted.await_count == 1
