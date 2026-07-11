from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender import api
from nonebot_plugin_htmlrender.api._default import (
    get_default_application,
    set_default_application,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nonebot_plugin_htmlrender.application import Application

pytestmark = pytest.mark.requires_browser

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
async def started_application() -> AsyncIterator[Application]:
    application = get_default_application()
    await application.startup()
    yield application
    await application.aclose()
    # Drop the closed instance so later tests rebuild from the factory.
    set_default_application(None)


async def test_render_text_produces_png(
    started_application: Application,
) -> None:
    assert started_application is api.get_default_application()

    artifact = await api.render_text("hello end-to-end")

    assert bytes(artifact)[: len(_PNG_MAGIC)] == _PNG_MAGIC
    assert artifact.media_type == "image/png"


async def test_render_html_and_markdown_produce_images(
    started_application: Application,
) -> None:
    assert started_application is api.get_default_application()

    html_artifact = await api.render_html("<h1>e2e</h1>")
    markdown_artifact = await api.render_markdown("# e2e")

    assert bytes(html_artifact)[: len(_PNG_MAGIC)] == _PNG_MAGIC
    assert bytes(markdown_artifact)[: len(_PNG_MAGIC)] == _PNG_MAGIC
