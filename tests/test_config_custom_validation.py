from typing import cast

from pydantic import BaseModel, Field
import pytest


@pytest.mark.parametrize(
    "engine",
    ["chromium", "firefox", "webkit"],
    ids=["test_chromium", "test_firefox", "test_webkit"],
)
def test_browser_engine_type_valid(engine):
    """Test valid browser engine types"""
    from nonebot_plugin_htmlrender.config import BrowserEngineType

    class TestConfig(BaseModel):
        browser: BrowserEngineType = Field(default="chromium")

    config = TestConfig(browser=cast(BrowserEngineType, engine))
    assert config.browser == engine


def test_browser_engine_type_invalid():
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


def test_browser_engine_type_validator_generator():
    from nonebot_plugin_htmlrender.config import BrowserEngineType

    """Test validator generator"""
    validators = list(BrowserEngineType.__get_validators__())
    assert len(validators) == 1
    assert validators[0] == BrowserEngineType.validate


def test_browser_engine_type_validate_method():
    from nonebot_plugin_htmlrender.config import BrowserEngineType

    """Test validate method directly"""
    # Test valid value
    assert BrowserEngineType.validate("chromium") == "chromium"

    # Test invalid value
    with pytest.raises(ValueError, match=r"Invalid browser type."):
        BrowserEngineType.validate("invalid")
