from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_data_source_wrappers_delegate_to_render_layer(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender import _compat  # noqa: PLC0415

    text = mocker.patch.object(
        _compat, "render_text", new=mocker.AsyncMock(return_value=b"a")
    )
    md = mocker.patch.object(
        _compat, "render_markdown", new=mocker.AsyncMock(return_value=b"b")
    )
    html = mocker.patch.object(
        _compat, "render_html", new=mocker.AsyncMock(return_value=b"c")
    )
    tpl = mocker.patch.object(
        _compat, "render_template", new=mocker.AsyncMock(return_value=b"d")
    )
    tpl_html = mocker.patch.object(
        _compat, "render_template_html", new=mocker.AsyncMock(return_value="e")
    )
    capture = mocker.patch.object(
        _compat, "capture_html_element", new=mocker.AsyncMock(return_value=b"f")
    )

    from nonebot_plugin_htmlrender import data_source  # noqa: PLC0415

    assert await data_source.text_to_pic("x", width=321) == b"a"
    assert await data_source.md_to_pic("md") == b"b"
    assert await data_source.html_to_pic("<p/>") == b"c"
    assert await data_source.template_to_html("templates", "a.html", title="x") == "e"
    assert await data_source.template_to_pic("templates", "a.html", {"x": 1}) == b"d"
    assert await data_source.capture_element("https://example.com", "#main") == b"f"

    text.assert_awaited_once()
    md.assert_awaited_once()
    html.assert_awaited_once()
    tpl.assert_awaited_once()
    tpl_html.assert_awaited_once_with(
        "templates",
        template_name="a.html",
        filters=None,
        title="x",
    )
    assert tpl.await_args is not None
    assert tpl.await_args.kwargs["pages"] == {"viewport": {"width": 500, "height": 10}}
    capture.assert_awaited_once()


@pytest.mark.anyio
async def test_backend_playwright_data_source_wrappers(
    mocker: MockerFixture,
) -> None:
    from nonebot_plugin_htmlrender.backend.playwright import (  # noqa: PLC0415
        data_source as pw_data_source,
    )

    render_text = mocker.patch.object(
        pw_data_source._operations,
        "render_text",
        new=mocker.AsyncMock(return_value=b"a"),
    )
    render_markdown = mocker.patch.object(
        pw_data_source._operations,
        "render_markdown",
        new=mocker.AsyncMock(return_value=b"b"),
    )
    render_template_html = mocker.patch.object(
        pw_data_source._operations,
        "render_template_html",
        new=mocker.AsyncMock(return_value="h"),
    )
    render_html = mocker.patch.object(
        pw_data_source._operations,
        "render_html",
        new=mocker.AsyncMock(return_value=b"c"),
    )
    render_template = mocker.patch.object(
        pw_data_source._operations,
        "render_template",
        new=mocker.AsyncMock(return_value=b"d"),
    )
    capture = mocker.patch.object(
        pw_data_source._operations,
        "capture_html_element",
        new=mocker.AsyncMock(return_value=b"e"),
    )

    assert await pw_data_source.text_to_pic("x") == b"a"
    assert await pw_data_source.md_to_pic("x") == b"b"
    assert await pw_data_source.template_to_html("t", "n") == "h"
    assert await pw_data_source.html_to_pic("<p/>") == b"c"
    assert await pw_data_source.template_to_pic("t", "n", {}) == b"d"
    assert await pw_data_source.capture_element("u", "#e") == b"e"
    assert pw_data_source.read_file is not None
    assert pw_data_source.read_tpl is not None

    render_text.assert_awaited_once()
    render_markdown.assert_awaited_once()
    render_template_html.assert_awaited_once()
    render_html.assert_awaited_once()
    render_template.assert_awaited_once()
    capture.assert_awaited_once()
