from dataclasses import dataclass
import os
import sys


@dataclass(frozen=True)
class MirrorSource:
    name: str
    url: str
    priority: int


# consts
PLUGINS_GROUP = "nonebot_plugin_htmlrender"
SCRIPTS_GROUP = "nonebot_plugin_htmlrender_scripts"
REQUIRES_PYTHON = (3, 9)
# SHELL = os.getenv("SHELL", "")
WINDOWS = sys.platform.startswith("win") or (sys.platform == "cli" and os.name == "nt")
# MINGW = sysconfig.get_platform().startswith("mingw")
# MACOS = sys.platform == "darwin"
MIRRORS = [
    MirrorSource("官方", "https://playwright.azureedge.net", 1),
    MirrorSource("淘宝", "https://registry.npmmirror.com/-/binary/playwright", 2),
]
BROWSER_ENGINE_TYPES = ["chromium", "firefox", "webkit"]
BROWSER_CHANNEL_TYPES = [
    "chromium",
    "chrome",
    "chrome-beta",
    "chrome-dev",
    "chrome-canary",
    "msedge",
    "msedge-beta",
    "msedge-dev",
    "msedge-canary",
    "firefox",
    "webkit",
]
