import pytest
import nonebot


@pytest.fixture(scope="session", autouse=True)
def load_bot():
    # 加载插件
    import nonebot_plugin_htmlrender

    nonebot.load_plugin("nonebot_plugin_htmlrender")
