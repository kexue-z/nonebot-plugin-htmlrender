from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
import sys
import sysconfig


class StrEnum(str, Enum):
    """字符串枚举基类，用于声明取值为字符串的枚举类型。"""


@dataclass(frozen=True)
class MirrorSource:
    """Playwright 浏览器二进制下载镜像源。

    Attributes:
        name: 镜像源展示名称。
        url: 镜像下载基础 URL。
        priority: 优先级，数值越小越优先尝试。
    """

    name: str
    url: str
    priority: int


SHELL = os.getenv("SHELL", "")
WINDOWS = sys.platform.startswith("win") or (sys.platform == "cli" and os.name == "nt")
MINGW = sysconfig.get_platform().startswith("mingw")
MACOS = sys.platform == "darwin"
MIRRORS = [
    MirrorSource("Taobao", "https://registry.npmmirror.com/-/binary/playwright", 1),
]


class RenderBackend(StrEnum):
    """Rendering backend selector.

    Values are consumed by plugin config / env vars.
    """

    SKIA = "skia"
    PLAYWRIGHT = "playwright"
    PILLOW = "pillow"
    HTMLKIT = "htmlkit"
    TAKUMI = "takumi"


class RenderStartupMode(StrEnum):
    """Plugin startup policy for render runtime initialization."""

    OFF = "off"
    WARMUP = "warmup"
    PROBE = "probe"


class BrowserEngine(StrEnum):
    """Playwright browser engine.

    Docs:
      - https://playwright.dev/python/docs/browsers
    """

    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class ChromiumChannel(StrEnum):
    """Chromium distribution channel for `BrowserType.launch(channel=...)`.

    Docs:
      - https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch
      - https://playwright.dev/python/docs/browsers
    """

    # "chromium" opts into the new headless mode (Playwright docs).
    CHROMIUM = "chromium"

    CHROME = "chrome"
    CHROME_BETA = "chrome-beta"
    CHROME_DEV = "chrome-dev"
    CHROME_CANARY = "chrome-canary"

    MSEDGE = "msedge"
    MSEDGE_BETA = "msedge-beta"
    MSEDGE_DEV = "msedge-dev"
    MSEDGE_CANARY = "msedge-canary"


class ResourceResolveMode(StrEnum):
    """模板中资源占位符的解析模式。"""

    OFF = "off"
    AUTO = "auto"
    STRICT = "strict"


class RemoteLocalResourcePolicy(StrEnum):
    """远程渲染时对本地资源的处理策略。"""

    PASSTHROUGH = "passthrough"
    FILEHOST = "filehost"
    ERROR = "error"


class LocalLocalResourcePolicy(StrEnum):
    """本地渲染时对本地资源的处理策略。"""

    FILE = "file"
    FILEHOST = "filehost"
    PASSTHROUGH = "passthrough"


__all__ = (
    "BrowserEngine",
    "ChromiumChannel",
    "LocalLocalResourcePolicy",
    "RemoteLocalResourcePolicy",
    "RenderBackend",
    "RenderStartupMode",
    "ResourceResolveMode",
)
