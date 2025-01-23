from collections.abc import Generator
from typing import Any, Callable, ClassVar, Optional

from nonebot import get_driver, get_plugin_config
from nonebot.compat import custom_validation
from pydantic import BaseModel, Field

from nonebot_plugin_htmlrender.consts import BROWSER_CHANNEL_TYPES, BROWSER_ENGINE_TYPES


@custom_validation
class BrowserEngineType(str):
    """Playwright浏览器引擎类型，支持的值由 BROWSER_ENGINE_TYPES 定义。"""

    ALLOWED_VALUES: ClassVar = BROWSER_ENGINE_TYPES

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


@custom_validation
class BrowserChannelType(str):
    """Playwright浏览器通道类型，支持的值由 BROWSER_CHANNEL_TYPES 定义。"""

    ALLOWED_VALUES: ClassVar = BROWSER_CHANNEL_TYPES

    @classmethod
    def __get_validators__(cls) -> Generator[Callable[..., Any], None, None]:
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> str:
        if value not in cls.ALLOWED_VALUES:
            raise ValueError(
                f"Invalid channel: {value!r}, must be one of {cls.ALLOWED_VALUES}"
            )
        return value


class Config(BaseModel):
    """插件配置类。"""

    htmlrender_browser: BrowserEngineType = Field(
        default="chromium",
        description="Playwright浏览器引擎类型，默认值为 'chromium'。",
    )
    htmlrender_download_host: Optional[str] = Field(
        default=None, description="下载Playwright浏览器时的主机地址。"
    )
    htmlrender_download_proxy: Optional[str] = Field(
        default=None, description="下载Playwright浏览器时的代理设置。"
    )
    htmlrender_proxy_host: Optional[str] = Field(
        default=None, description="Playwright浏览器使用的代理主机地址。"
    )
    htmlrender_proxy_host_bypass: Optional[str] = Field(
        default=None, description="Playwright浏览器代理的绕过地址。"
    )
    htmlrender_browser_channel: Optional[BrowserChannelType] = Field(
        default=None, description="Playwright浏览器通道类型。"
    )
    htmlrender_browser_executable_path: Optional[str] = Field(
        default=None, description="Playwright浏览器可执行文件的路径。"
    )
    htmlrender_connect_over_cdp: Optional[str] = Field(
        default=None, description="通过 CDP 连接Playwright浏览器的端点地址。"
    )


global_config = get_driver().config
plugin_config = get_plugin_config(Config)
