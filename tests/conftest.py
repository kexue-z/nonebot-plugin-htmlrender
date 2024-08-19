import nonebot
import pytest
from nonebug import App


@pytest.fixture
def app():
    nonebot.require("nonebot_plugin_htmlrender")

    yield App()
