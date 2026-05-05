import pytest


def test_playwright_config_normalizes_empty_executable_path() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )

    cfg = PlaywrightConfig.model_validate({"executable_path": " . "})

    assert cfg.executable_path is None


def test_playwright_config_rejects_channel_for_non_chromium() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.consts import (  # noqa: PLC0415
        BrowserEngine,
        ChromiumChannel,
    )

    with pytest.raises(ValueError, match="channel"):
        PlaywrightConfig(
            engine=BrowserEngine.FIREFOX,
            channel=ChromiumChannel.CHROME,
        )


def test_playwright_config_rejects_multiple_remote_modes() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
        RemoteCDPConfig,
        RemoteWSConfig,
    )

    with pytest.raises(ValueError, match="only one remote mode can be enabled"):
        PlaywrightConfig(
            connect_ws=RemoteWSConfig(endpoint="ws://localhost:3000/ws"),
            connect_cdp=RemoteCDPConfig(endpoint="http://localhost:9222"),
        )


def test_playwright_config_rejects_non_chromium_cdp() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
        RemoteCDPConfig,
    )
    from nonebot_plugin_htmlrender.consts import BrowserEngine  # noqa: PLC0415

    with pytest.raises(ValueError, match="CDP connection requires"):
        PlaywrightConfig(
            engine=BrowserEngine.WEBKIT,
            connect_cdp=RemoteCDPConfig(endpoint="http://localhost:9222"),
        )


def test_playwright_config_accepts_resource_resolution_options() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )
    from nonebot_plugin_htmlrender.consts import (  # noqa: PLC0415
        LocalLocalResourcePolicy,
        RemoteLocalResourcePolicy,
        ResourceResolveMode,
    )

    cfg = PlaywrightConfig(
        resource_resolve_mode=ResourceResolveMode.AUTO,
        remote_local_resource_policy=RemoteLocalResourcePolicy.FILEHOST,
        local_local_resource_policy=LocalLocalResourcePolicy.FILE,
    )

    assert cfg.resource_resolve_mode is ResourceResolveMode.AUTO
    assert cfg.remote_local_resource_policy is RemoteLocalResourcePolicy.FILEHOST
    assert cfg.local_local_resource_policy is LocalLocalResourcePolicy.FILE


def test_playwright_config_normalizes_filehost_request_header_salt() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )

    defaulted = PlaywrightConfig.model_validate({"filehost_request_header_salt": "   "})
    assert (
        defaulted.filehost_request_header_salt
        == "nonebot-plugin-htmlrender:filehost:guard:v1"
    )

    custom = PlaywrightConfig.model_validate(
        {"filehost_request_header_salt": "custom-salt"}
    )
    assert custom.filehost_request_header_salt == "custom-salt"


def test_playwright_config_normalizes_filehost_prewarm_fields() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )

    cfg = PlaywrightConfig.model_validate(
        {
            "filehost_prewarm_paths": "assets",
            "filehost_prewarm_extensions": "css, png, .woff2, ",
        }
    )

    assert len(cfg.filehost_prewarm_paths) == 1
    assert str(cfg.filehost_prewarm_paths[0]) == "assets"
    assert cfg.filehost_prewarm_extensions == [".css", ".png", ".woff2"]


def test_playwright_config_normalizes_filehost_header_fields() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )

    cfg = PlaywrightConfig.model_validate(
        {
            "filehost_request_header_name": "   ",
            "filehost_request_header_value": "   ",
        }
    )
    assert cfg.filehost_request_header_name == "X-HTMLRender-Filehost-Request"
    assert cfg.filehost_request_header_value is None

    cfg2 = PlaywrightConfig.model_validate(
        {
            "filehost_allowed_paths": "assets",
            "filehost_prewarm_paths": "assets2",
        }
    )
    assert len(cfg2.filehost_allowed_paths) == 1
    assert len(cfg2.filehost_prewarm_paths) == 1


def test_playwright_config_rejects_invalid_engine_and_channel() -> None:
    from nonebot_plugin_htmlrender.backend.playwright.config import (  # noqa: PLC0415
        PlaywrightConfig,
    )

    with pytest.raises(ValueError, match=r"(invalid engine|Input should be)"):
        PlaywrightConfig.model_validate({"engine": "invalid-engine"})

    with pytest.raises(ValueError, match=r"(invalid channel|Input should be)"):
        PlaywrightConfig.model_validate({"channel": "invalid-channel"})
