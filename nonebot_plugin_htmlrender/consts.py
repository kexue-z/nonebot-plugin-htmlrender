from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
import sys

# Docs (Playwright Browsers):
# https://playwright.dev/python/docs/browsers
#
# Docs (Playwright BrowserType.launch / channel option):
# https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch


@dataclass(frozen=True)
class MirrorSource:
    name: str
    url: str
    priority: int


# SHELL = os.getenv("SHELL", "")
WINDOWS = sys.platform.startswith("win") or (sys.platform == "cli" and os.name == "nt")
# MINGW = sysconfig.get_platform().startswith("mingw")
# MACOS = sys.platform == "darwin"
MIRRORS = [
    MirrorSource("Default", "https://playwright.azureedge.net", 1),
    MirrorSource("Taobao", "https://registry.npmmirror.com/-/binary/playwright", 2),
]


class RenderBackend(StrEnum):
    """Rendering backend selector.

    Values are consumed by plugin config / env vars.
    """

    SKIA = "skia"
    PLAYWRIGHT = "playwright"
    PILLOW = "pillow"


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


__all__ = (
    "BrowserEngine",
    "ChromiumChannel",
    "RenderBackend",
)
