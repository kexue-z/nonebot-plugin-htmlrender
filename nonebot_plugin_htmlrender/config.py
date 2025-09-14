from pathlib import Path
from typing import Any, Optional

from nonebot import get_driver, get_plugin_config
from nonebot.compat import model_validator
from nonebot.log import logger
import nonebot_plugin_localstore as store
from pydantic import BaseModel, Field

from nonebot_plugin_htmlrender.consts import BROWSER_CHANNEL_TYPES, BROWSER_ENGINE_TYPES

plugin_cache_dir: Path = store.get_plugin_cache_dir()
plugin_config_dir: Path = store.get_plugin_config_dir()
plugin_data_dir: Path = store.get_plugin_data_dir()


class Config(BaseModel):
    """插件配置类。"""

    htmlrender_browser: str = Field(
        default="chromium",
        description="Playwright浏览器引擎类型，默认值为 'chromium'。",
    )
    htmlrender_storage_path: Path = Field(
        default=plugin_data_dir,
        description="存储路径，不填则使用 `nonebot-plugin-localstore` 管理",
    )
    htmlrender_cache_path: Path = Field(
        default=plugin_cache_dir,
        description="缓存路径，不填则使用 `nonebot-plugin-localstore` 管理",
    )
    htmlrender_config_path: Path = Field(
        default=plugin_config_dir,
        description="配置路径，不填则使用 `nonebot-plugin-localstore` 管理",
    )
    htmlrender_shutdown_browser_on_exit: bool = Field(
        default=True,
        description="在插件关闭时关闭浏览器实例，在连接到远程浏览器时默认为 False。",
    )
    htmlrender_ci_mode: bool = Field(
        default=False,
        description="启用CI模式，跳过浏览器安装和环境变量",
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
    htmlrender_browser_executable_path: Optional[Path] = Field(
        default=None, description="Playwright浏览器可执行文件的路径。"
    )
    htmlrender_connect_over_cdp: Optional[str] = Field(
        default=None, description="通过 CDP 连接Playwright浏览器的端点地址。"
    )
    htmlrender_connect: Optional[str] = Field(
        default=None, description="通过Playwright协议连接Playwright浏览器的端点地址。"
    )
    htmlrender_browser_args: Optional[str] = Field(
        default=None, description="Playwright 浏览器启动参数。"
    )

    @model_validator(mode="after")
    @classmethod
    def check_browser_channel(cls, data: Any) -> Any:
        browser_channel = (
            data.get("htmlrender_browser_channel")
            if isinstance(data, dict)
            else getattr(data, "htmlrender_browser_channel", None)
        )

        if browser_channel is not None and browser_channel not in BROWSER_CHANNEL_TYPES:
            raise ValueError(
                f"Invalid browser channel type. Must be one of {BROWSER_CHANNEL_TYPES}"
            )
        return data

    @model_validator(mode="after")
    @classmethod
    def check_browser(cls, data: Any) -> Any:
        browser = (
            data.get("htmlrender_browser", "chromium")
            if isinstance(data, dict)
            else getattr(data, "htmlrender_browser", "chromium")
        )

        if browser not in BROWSER_ENGINE_TYPES:
            raise ValueError(
                f"Invalid browser type. Must be one of {BROWSER_ENGINE_TYPES}"
            )
        return data


global_config = get_driver().config
plugin_config = get_plugin_config(Config)

if plugin_config.htmlrender_ci_mode:
    logger.info(
        "CI mode enabled, skipping browser installation and environment variable setup."
    )
