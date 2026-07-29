from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from nonebot.compat import field_validator, model_validator
from pydantic import BaseModel, ConfigDict, Field

from nonebot_plugin_htmlrender.resources.config import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)

__all__ = [
    "BrowserEngine",
    "ChromiumChannel",
    "PlaywrightConfig",
    "RemoteCDPConfig",
    "RemoteWSConfig",
]


class BrowserEngine(str, Enum):
    """Playwright browser engine."""

    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class ChromiumChannel(str, Enum):
    """Chromium distribution channel accepted by Playwright."""

    CHROMIUM = "chromium"
    CHROME = "chrome"
    CHROME_BETA = "chrome-beta"
    CHROME_DEV = "chrome-dev"
    CHROME_CANARY = "chrome-canary"
    MSEDGE = "msedge"
    MSEDGE_BETA = "msedge-beta"
    MSEDGE_DEV = "msedge-dev"
    MSEDGE_CANARY = "msedge-canary"


def _get(obj: object, name: str, default: object = None) -> object:
    """从对象或映射中安全获取属性值。

    Args:
        obj: 目标对象，可以是 Mapping 类型或普通对象。
        name: 要获取的属性名。
        default: 属性不存在时返回的默认值。

    Returns:
        属性值，若不存在则返回 default。
    """
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


class RemoteWSConfig(BaseModel):
    """远程 Playwright WebSocket 连接配置。"""

    endpoint: str | None = Field(default=None)

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class RemoteCDPConfig(BaseModel):
    """远程 Playwright CDP 连接配置。"""

    endpoint: str | None = Field(default=None)

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class PlaywrightConfig(BaseModel):
    """Playwright 后端的全部插件配置项。"""

    engine: BrowserEngine = Field(default=BrowserEngine.CHROMIUM)
    channel: ChromiumChannel | None = Field(default=None)
    executable_path: Path | None = Field(default=None)
    launch_args: str | None = Field(default=None)
    proxy_server: str | None = Field(default=None)
    proxy_bypass: str | None = Field(default=None)
    connect_ws: RemoteWSConfig = Field(default_factory=RemoteWSConfig)
    connect_cdp: RemoteCDPConfig = Field(default_factory=RemoteCDPConfig)
    install_mirror: str | None = Field(default=None)
    install_proxy: str | None = Field(default=None)
    skip_browser_install: bool = Field(default=False)
    cleanup_legacy_cache: bool = Field(default=False)
    close_on_exit: bool = Field(default=True)
    storage_path: Path | None = Field(default=None)
    resource_resolve_mode: ResourceResolveMode = Field(default=ResourceResolveMode.AUTO)
    remote_local_resource_policy: RemoteLocalResourcePolicy = Field(
        default=RemoteLocalResourcePolicy.MEMORY
    )
    local_local_resource_policy: LocalLocalResourcePolicy = Field(
        default=LocalLocalResourcePolicy.FILE
    )

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    @field_validator("executable_path", mode="before")
    @classmethod
    def _normalize_executable_path(cls, v: object) -> Path | None:
        """规范化浏览器可执行文件路径，将空值或无效路径转换为 None。"""
        if v is None:
            return None

        if isinstance(v, Path):
            return None if v == Path() else v

        s = v.strip() if isinstance(v, str) else str(v).strip()
        if not s or s == ".":
            return None
        return Path(s)

    @model_validator(mode="before")
    @classmethod
    def validate_playwright_config(cls, data: Any) -> Any:
        """验证 Playwright 配置的合法性。

        检查引擎类型、channel 兼容性以及远程连接模式的互斥约束。

        Raises:
            ValueError: 配置项不合法或存在冲突时抛出。
        """
        engine_raw = _get(data, "engine", BrowserEngine.CHROMIUM)
        channel_raw = _get(data, "channel")
        connect_ws = _get(data, "connect_ws")
        connect_cdp = _get(data, "connect_cdp")

        ws_endpoint = _get(connect_ws, "endpoint")
        cdp_endpoint = _get(connect_cdp, "endpoint")

        try:
            engine = BrowserEngine(engine_raw)
        except ValueError:
            allowed = tuple(v.value for v in BrowserEngine)
            raise ValueError(
                f"[playwright] invalid engine: {engine_raw!r}. Must be one of {allowed}"
            ) from None

        if channel_raw is not None:
            if engine is not BrowserEngine.CHROMIUM:
                raise ValueError(
                    "[playwright] `channel` is only supported when `engine='chromium'`."
                )
            try:
                ChromiumChannel(channel_raw)
            except ValueError:
                allowed = tuple(v.value for v in ChromiumChannel)
                raise ValueError(
                    f"[playwright] invalid channel: {channel_raw!r}. Must be one of {allowed}"
                ) from None

        if ws_endpoint and cdp_endpoint:
            raise ValueError(
                "[playwright] only one remote mode can be enabled at a time: "
                "`render.provider_config.connect_ws.endpoint` or "
                "`render.provider_config.connect_cdp.endpoint`."
            )

        if cdp_endpoint and engine is not BrowserEngine.CHROMIUM:
            raise ValueError(
                "[playwright] CDP connection requires "
                "`render.provider_config.engine='chromium'`."
            )

        return data
