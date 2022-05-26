import pytest
from pathlib import Path
from nonebug.app import App


@pytest.fixture
async def app(
    nonebug_init: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> App:
    import nonebot

    nonebot.load_plugin("nonebot_plugin_htmlrender")

    import nonebot_plugin_htmlrender

    return App(monkeypatch)
