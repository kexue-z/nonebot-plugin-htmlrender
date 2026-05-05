"""Backward-compatible import path.

All symbols re-exported from :mod:`nonebot_plugin_htmlrender._compat`.
"""

from nonebot_plugin_htmlrender._compat import (
    _launch as _launch,
)
from nonebot_plugin_htmlrender._compat import (
    clean_playwright_cache as clean_playwright_cache,
)
from nonebot_plugin_htmlrender._compat import (
    get_browser as get_browser,
)
from nonebot_plugin_htmlrender._compat import (
    get_new_page as get_new_page,
)
from nonebot_plugin_htmlrender._compat import (
    reconcile_legacy_playwright_cache as reconcile_legacy_playwright_cache,
)
from nonebot_plugin_htmlrender._compat import (
    shutdown_htmlrender as shutdown_htmlrender,
)
from nonebot_plugin_htmlrender._compat import (
    startup_htmlrender as startup_htmlrender,
)

__all__ = [
    "_launch",
    "clean_playwright_cache",
    "get_browser",
    "get_new_page",
    "reconcile_legacy_playwright_cache",
    "shutdown_htmlrender",
    "startup_htmlrender",
]
