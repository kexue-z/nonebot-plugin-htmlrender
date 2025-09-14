import gc

import anyio
import nonebot
from nonebug import NONEBOT_INIT_KWARGS
import pytest
from pytest_asyncio import is_async_test


def pytest_configure(config: pytest.Config) -> None:
    config.stash[NONEBOT_INIT_KWARGS] = {
        "superusers": {"10001"},
        "command_start": {""},
        "log_level": "DEBUG",
        "htmlrender_ci_mode": True,
    }


def pytest_collection_modifyitems(items: list[pytest.Item]):
    pytest_asyncio_tests = (item for item in items if is_async_test(item))
    session_scope_marker = pytest.mark.asyncio(loop_scope="session")
    for async_test in pytest_asyncio_tests:
        async_test.add_marker(session_scope_marker, append=False)


@pytest.fixture(scope="session", autouse=True)
async def after_nonebot_init(after_nonebot_init: None):
    nonebot.require("nonebot_plugin_htmlrender")


@pytest.fixture(scope="session", autouse=True)
async def _cleanup_playwright_session():
    from nonebot_plugin_htmlrender import shutdown_htmlrender

    yield

    await shutdown_htmlrender()

    gc.collect()
    gc.collect()

    await anyio.lowlevel.checkpoint()
