from typing import Optional

from pydantic import BaseModel, Field
from nonebot import get_driver, get_plugin_config


class Config(BaseModel):
    htmlrender_browser: Optional[str] = Field(default="chromium")
    htmlrender_download_host: Optional[str] = Field(default=None)
    htmlrender_proxy_host: Optional[str] = Field(default=None)
    htmlrender_browser_channel: Optional[str] = Field(default=None)
    htmlrender_browser_executable_path: Optional[str] = Field(default=None)
    htmlrender_connect_over_cdp: Optional[str] = Field(default=None)


global_config = get_driver().config
plugin_config = get_plugin_config(Config)
