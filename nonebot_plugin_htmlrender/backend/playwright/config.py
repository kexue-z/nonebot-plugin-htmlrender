from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from nonebot import get_plugin_config
from nonebot.compat import field_validator, model_validator
from pydantic import BaseModel, Field

from nonebot_plugin_htmlrender.consts import (
    BrowserEngine,
    ChromiumChannel,
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    ResourceResolveMode,
)


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
        return cast("Mapping[str, object]", obj).get(name, default)
    return getattr(obj, name, default)


class RemoteWSConfig(BaseModel):
    """远程 Playwright WebSocket 连接配置。"""

    endpoint: str | None = Field(default=None)


class RemoteCDPConfig(BaseModel):
    """远程 Playwright CDP 连接配置。"""

    endpoint: str | None = Field(default=None)


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
    resource_resolve_mode: ResourceResolveMode = Field(default=ResourceResolveMode.AUTO)
    remote_local_resource_policy: RemoteLocalResourcePolicy = Field(
        default=RemoteLocalResourcePolicy.MEMORY
    )
    local_local_resource_policy: LocalLocalResourcePolicy = Field(
        default=LocalLocalResourcePolicy.FILE
    )
    filehost_allow_any_path: bool = Field(default=False)
    filehost_allowed_paths: list[Path] = Field(default_factory=list)
    filehost_prewarm_paths: list[Path] = Field(default_factory=list)
    filehost_prewarm_enabled: bool = Field(default=True)
    filehost_prewarm_max_files: int = Field(default=256, ge=0)
    filehost_cache_ttl_seconds: float = Field(default=300.0, ge=0.0)
    filehost_prewarm_extensions: list[str] = Field(
        default_factory=lambda: [
            ".css",
            ".js",
            ".mjs",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".svg",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
            ".otf",
            ".map",
        ]
    )
    filehost_request_header_name: str = Field(default="X-HTMLRender-Filehost-Request")
    filehost_request_header_value: str | None = Field(default=None)
    filehost_request_header_salt: str = Field(
        default="nonebot-plugin-htmlrender:filehost:guard:v1"
    )

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

    @field_validator("filehost_allowed_paths", mode="before")
    @classmethod
    def _normalize_filehost_allowed_paths(cls, v: object) -> object:
        """规范化 filehost 允许路径列表，将单个路径或 None 转换为列表。"""
        if v is None:
            return []
        if isinstance(v, (str, Path)):
            return [v]
        return v

    @field_validator("filehost_prewarm_paths", mode="before")
    @classmethod
    def _normalize_filehost_prewarm_paths(cls, v: object) -> object:
        """规范化 filehost 预热路径列表，将单个路径或 None 转换为列表。"""
        if v is None:
            return []
        if isinstance(v, (str, Path)):
            return [v]
        return v

    @field_validator("filehost_prewarm_extensions", mode="before")
    @classmethod
    def _normalize_filehost_prewarm_extensions(cls, v: object) -> list[str]:
        """规范化并去重 filehost 预热文件扩展名，确保以点号开头且小写。"""
        if v is None:
            return []
        if isinstance(v, str):
            values = [part.strip() for part in v.split(",")]
        elif isinstance(v, Iterable):
            values = [str(item).strip() for item in v]
        else:
            values = [str(v).strip()]
        normalized: list[str] = []
        for item in values:
            if not item:
                continue
            ext = item if item.startswith(".") else f".{item}"
            normalized.append(ext.lower())
        # keep order while removing duplicates
        return list(dict.fromkeys(normalized))

    @field_validator("filehost_request_header_name", mode="before")
    @classmethod
    def _normalize_filehost_request_header_name(cls, v: object) -> str:
        """规范化 filehost 请求头名称，空值时回退到默认值。"""
        text = str(v).strip() if v is not None else ""
        if not text:
            return "X-HTMLRender-Filehost-Request"
        return text

    @field_validator("filehost_request_header_value", mode="before")
    @classmethod
    def _normalize_filehost_request_header_value(cls, v: object) -> str | None:
        """规范化 filehost 请求头值，空字符串转换为 None。"""
        if v is None:
            return None
        text = str(v).strip()
        return text or None

    @field_validator("filehost_request_header_salt", mode="before")
    @classmethod
    def _normalize_filehost_request_header_salt(cls, v: object) -> str:
        """规范化 filehost 请求头盐值，空值时回退到默认值。"""
        text = str(v).strip() if v is not None else ""
        if not text:
            return "nonebot-plugin-htmlrender:filehost:guard:v1"
        return text

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
                "`render_playwright.connect_ws.endpoint` or `render_playwright.connect_cdp.endpoint`."
            )

        if cdp_endpoint and engine is not BrowserEngine.CHROMIUM:
            raise ValueError(
                "[playwright] CDP connection requires `render_playwright.engine='chromium'`."
            )

        return data


class PlaywrightPluginConfig(BaseModel):
    """聚合 ``render_playwright.*`` 命名空间下的配置入口。"""

    render_playwright: PlaywrightConfig = Field(default_factory=PlaywrightConfig)


def get_playwright_config() -> PlaywrightConfig:
    """获取当前 Playwright 配置。"""
    return get_plugin_config(PlaywrightPluginConfig).render_playwright
