from collections.abc import Generator
from typing import Any, Callable, ClassVar, Optional

from nonebot import get_driver, get_plugin_config
from nonebot.compat import custom_validation
from pydantic import BaseModel, Field


@custom_validation
class BrowserEngineType(str):
    ALLOWED_VALUES: ClassVar = ["chromium", "firefox", "webkit"]

    @classmethod
    def __get_validators__(cls) -> Generator[Callable[..., Any], None, None]:
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> str:
        if value not in cls.ALLOWED_VALUES:
            raise ValueError(
                f"Invalid browser type: {value!r}, must be one of {cls.ALLOWED_VALUES}"
            )
        return value


class Config(BaseModel):
    htmlrender_browser: BrowserEngineType = Field(default="chromium")
    htmlrender_download_host: Optional[str] = Field(default=None)
    htmlrender_proxy_host: Optional[str] = Field(default=None)
    htmlrender_browser_channel: Optional[str] = Field(default=None)
    htmlrender_browser_executable_path: Optional[str] = Field(default=None)
    htmlrender_connect_over_cdp: Optional[str] = Field(default=None)


global_config = get_driver().config
plugin_config = get_plugin_config(Config)
