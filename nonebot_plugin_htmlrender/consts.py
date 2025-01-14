import os
import sys

# consts
PLUGINS_GROUP = "nonebot_plugin_htmlrender"
SCRIPTS_GROUP = "nonebot_plugin_htmlrender_scripts"
REQUIRES_PYTHON = (3, 9)
# SHELL = os.getenv("SHELL", "")
WINDOWS = sys.platform.startswith("win") or (sys.platform == "cli" and os.name == "nt")
# MINGW = sysconfig.get_platform().startswith("mingw")
# MACOS = sys.platform == "darwin"
