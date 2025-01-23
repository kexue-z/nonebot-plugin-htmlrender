from typing import cast

from pydantic import BaseModel, Field
import pytest

BROWSER_ENGINE_TYPES = ["chromium", "firefox", "webkit"]
BROWSER_CHANNEL_TYPES = [
    "chromium",
    "chrome",
    "chrome-beta",
    "chrome-dev",
    "chrome-canary",
    "msedge",
    "msedge-beta",
    "msedge-dev",
    "msedge-canary",
    "firefox",
    "webkit",
]


class TestBrowserEngineType:
    @pytest.mark.parametrize(
        "engine",
        BROWSER_ENGINE_TYPES,
        ids=[f"test_{engine}" for engine in BROWSER_ENGINE_TYPES],
    )
    def test_browser_engine_type_valid(self, engine):
        """Test valid browser engine types"""
        from nonebot_plugin_htmlrender.config import BrowserEngineType

        class TestConfig(BaseModel):
            browser: BrowserEngineType = Field(default="chromium")

        config = TestConfig(browser=cast(BrowserEngineType, engine))
        assert config.browser == engine

    def test_browser_engine_type_invalid(self):
        """Test invalid browser engine type"""
        from nonebot_plugin_htmlrender.config import BrowserEngineType

        class TestConfig(BaseModel):
            browser: BrowserEngineType = Field(default="chromium")

        with pytest.raises(
            ValueError,
            match=r"Invalid browser type."
            r"*must be one of \['chromium', 'firefox', 'webkit'\]",
        ):
            TestConfig(browser=cast(BrowserEngineType, "invalid"))

    def test_browser_engine_type_validator_generator(self):
        """Test validator generator"""
        from nonebot_plugin_htmlrender.config import BrowserEngineType

        validators = list(BrowserEngineType.__get_validators__())
        assert len(validators) == 1
        assert validators[0] == BrowserEngineType.validate

    def test_browser_engine_type_validate_method(self):
        """Test validate method directly"""
        from nonebot_plugin_htmlrender.config import BrowserEngineType

        # Test valid value
        assert BrowserEngineType.validate("chromium") == "chromium"

        # Test invalid value
        with pytest.raises(ValueError, match=r"Invalid browser type."):
            BrowserEngineType.validate("invalid")


class TestBrowserChannelType:
    @pytest.mark.parametrize(
        "channel",
        BROWSER_CHANNEL_TYPES,
        ids=[f"test_{channel}" for channel in BROWSER_CHANNEL_TYPES],
    )
    def test_browser_channel_type_valid(self, channel):
        """Test valid browser channel types"""
        from nonebot_plugin_htmlrender.config import BrowserChannelType

        class TestConfig(BaseModel):
            channel: BrowserChannelType = Field(default="chromium")

        config = TestConfig(channel=cast(BrowserChannelType, channel))
        assert config.channel == channel

    def test_browser_channel_type_invalid(self):
        """Test invalid browser channel type"""
        from nonebot_plugin_htmlrender.config import BrowserChannelType

        class TestConfig(BaseModel):
            channel: BrowserChannelType = Field(default="chromium")

        with pytest.raises(
            ValueError,
            match=r"Invalid channel: 'invalid', must be one of .*",
        ):
            TestConfig(channel=cast(BrowserChannelType, "invalid"))

    def test_browser_channel_type_validator_generator(self):
        """Test validator generator"""
        from nonebot_plugin_htmlrender.config import BrowserChannelType

        validators = list(BrowserChannelType.__get_validators__())
        assert len(validators) == 1
        assert validators[0] == BrowserChannelType.validate

    def test_browser_channel_type_validate_method(self):
        """Test validate method directly"""
        from nonebot_plugin_htmlrender.config import BrowserChannelType

        # Test valid value
        assert BrowserChannelType.validate("chromium") == "chromium"

        # Test invalid value
        with pytest.raises(
            ValueError, match=r"Invalid channel: 'invalid', must be one of .*"
        ):
            BrowserChannelType.validate("invalid")
