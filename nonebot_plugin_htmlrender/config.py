from typing import Optional
from typing_extensions import Self

from nonebot import get_driver, get_plugin_config
from pydantic import BaseModel, Field

from nonebot_plugin_htmlrender.compat import model_validator
from nonebot_plugin_htmlrender.consts import BROWSER_CHANNEL_TYPES, BROWSER_ENGINE_TYPES


class Config(BaseModel):
    """插件配置类。"""

    htmlrender_browser: str = Field(
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
    htmlrender_browser_channel: Optional[str] = Field(
        default=None, description="Playwright浏览器通道类型。"
    )
    htmlrender_browser_executable_path: Optional[str] = Field(
        default=None, description="Playwright浏览器可执行文件的路径。"
    )
    htmlrender_connect_over_cdp: Optional[str] = Field(
        default=None, description="通过 CDP 连接Playwright浏览器的端点地址。"
    )

    @model_validator(mode="after")
    def check_browser_channel(self) -> Self:
        if (
            self.htmlrender_browser_channel is not None
            and self.htmlrender_browser_channel not in BROWSER_CHANNEL_TYPES
        ):
            raise ValueError(
                f"Invalid browser channel type. Must be one of {BROWSER_CHANNEL_TYPES}"
            )
        return self

    @model_validator(mode="after")
    def check_browser(self) -> Self:
        if self.htmlrender_browser not in BROWSER_ENGINE_TYPES:
            raise ValueError(
                f"Invalid browser type. Must be one of {BROWSER_ENGINE_TYPES}"
            )
        return self


global_config = get_driver().config
plugin_config = get_plugin_config(Config)
