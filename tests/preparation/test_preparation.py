from __future__ import annotations

from dataclasses import replace
import math
import threading
from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender.preparation import (
    PreparedAsset,
    RasterOptions,
    RenderRequirement,
    prepare_html,
)
from nonebot_plugin_htmlrender.rendering import (
    InvalidRenderRequest,
    PreparationError,
    ResourceResolutionError,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any, Literal

    from nonebot_plugin_htmlrender.preparation.models import PreparedHtml
    from nonebot_plugin_htmlrender.preparation.service import DefaultHtmlPreparer


def test_prepare_html_preserves_document_and_extracts_css() -> None:
    prepared = prepare_html(
        "<style>.card { color: red }</style><main class='card'>ok</main>",
        stylesheets=[".logo { background: url(https://cdn.example/logo.png) }"],
        assets=[PreparedAsset("memory://icon", b"icon", "image/png")],
    )
    assert [stylesheet.embedded for stylesheet in prepared.stylesheets] == [False, True]
    assert prepared.assets[0].source == "memory://icon"
    assert RenderRequirement.NETWORK in prepared.requirements


def test_prepare_html_detects_script_and_local_resources() -> None:
    prepared = prepare_html('<script>run()</script><img src="./avatar.png">')
    assert prepared.requirements == frozenset(
        {RenderRequirement.JAVASCRIPT, RenderRequirement.LOCAL_RESOURCE}
    )


def test_prepare_html_captures_declared_base_href_semantics() -> None:
    prepared = prepare_html(
        '<base href="assets/"><img src="a.png">',
        base_url="https://cdn.example/cards/card.html",
    )
    # declared_href is captured verbatim; resolution against the preparation
    # base happens lazily.
    assert prepared.document_base.declared_href == "assets/"
    assert prepared.document_base.resolve() == "https://cdn.example/cards/assets/"


def test_document_base_relative_href_resolves_against_execution_fallback() -> None:
    # No preparation base URL, but a relative <base href> and an
    # execution-time fallback document URL: resolve() combines them.
    prepared = prepare_html('<base href="assets/"><img src="a.png">')
    assert prepared.document_base.preparation_base_url is None
    resolved = prepared.document_base.resolve(
        fallback_base_url="https://render.example/cards/card.html"
    )
    assert resolved == "https://render.example/cards/assets/"


def test_first_base_with_href_attribute_wins_even_when_empty() -> None:
    # An explicit empty href="" is a declared base distinct from an
    # undeclared one; it resolves to the document URL and a later <base>
    # must not override it.
    prepared = prepare_html(
        '<base href=""><base href="late/"><img src="a.png">',
        base_url="https://example.test/cards/card.html",
    )
    assert prepared.document_base.declared_href == ""
    assert prepared.document_base.resolve() == "https://example.test/cards/card.html"

    undeclared = prepare_html(
        '<img src="a.png">',
        base_url="https://example.test/cards/card.html",
    )
    assert undeclared.document_base.declared_href is None


def test_structure_snapshot_survives_dataclasses_replace() -> None:
    # Execution-time asset staging uses dataclasses.replace and must keep the
    # preparation-time parse results without re-parsing the markup.
    prepared = prepare_html(
        '<base href="assets/"><img src="a.png">',
        base_url="https://cdn.example/cards/card.html",
    )
    staged = replace(prepared, assets=())
    assert staged.structure is prepared.structure
    assert staged.document_base is prepared.document_base
    assert staged.structure.references == ("a.png",)
    assert staged.structure.base_tag is not None


@pytest.mark.parametrize(
    ("html", "base_url"),
    [
        ("<img src='http://['>", None),
        ("<p>plain</p>", "http://["),
    ],
)
def test_prepare_html_translates_invalid_resource_urls(
    html: str,
    base_url: str | None,
) -> None:
    with pytest.raises(PreparationError, match="Invalid HTML preparation input"):
        prepare_html(html, base_url=base_url)


@pytest.mark.parametrize("ratio", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_raster_options_reject_invalid_device_pixel_ratio(ratio: float) -> None:
    with pytest.raises(InvalidRenderRequest, match="finite and positive"):
        RasterOptions(device_pixel_ratio=ratio)


def test_raster_options_use_stable_validation_errors() -> None:
    with pytest.raises(InvalidRenderRequest, match="dimensions"):
        RasterOptions(width=0)
    with pytest.raises(InvalidRenderRequest, match="dimensions"):
        RasterOptions(height=-1)
    with pytest.raises(InvalidRenderRequest, match="format"):
        RasterOptions(format=cast("Literal['png', 'jpeg']", "gif"))
    with pytest.raises(InvalidRenderRequest, match="only supported for JPEG"):
        RasterOptions(quality=80)
    with pytest.raises(InvalidRenderRequest, match="between 0 and 100"):
        RasterOptions(format="jpeg", quality=101)


async def test_prepare_text_uses_injected_template_and_reader(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
) -> None:
    css = tmp_path / "text.css"
    css.write_text(".text { color: rebeccapurple; }", encoding="utf-8")
    prepared = await preparer.prepare_text("<hello>", css_path=str(css))
    assert "&lt;hello&gt;" in prepared.html
    assert prepared.stylesheets[0].base_url == css.resolve().as_uri()


async def test_prepare_markdown_reads_source_and_marks_math(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
) -> None:
    source = tmp_path / "document.md"
    source.write_text(
        "# Title\n\n$$x^2$$\n\n<blockquote><p>Thinking</p></blockquote>",
        encoding="utf-8",
    )
    prepared = await preparer.prepare_markdown(markdown_path=str(source))
    assert "<h1>Title</h1>" in prepared.html
    assert "<blockquote><p>Thinking</p></blockquote>" in prepared.html
    assert "&lt;h1&gt;" not in prepared.html
    assert RenderRequirement.JAVASCRIPT in prepared.requirements


async def test_cpu_bound_preparation_runs_outside_the_event_loop(
    preparer: DefaultHtmlPreparer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_htmlrender.preparation import service  # noqa: PLC0415

    event_loop_thread = threading.get_ident()
    parser_threads: list[int] = []
    markdown_threads: list[int] = []
    original_prepare_html = service.prepare_html
    original_markdown = service.markdown.markdown

    def recording_prepare_html(*args: Any, **kwargs: Any) -> PreparedHtml:
        parser_threads.append(threading.get_ident())
        return original_prepare_html(*args, **kwargs)

    def recording_markdown(*args: Any, **kwargs: Any) -> str:
        markdown_threads.append(threading.get_ident())
        return original_markdown(*args, **kwargs)

    monkeypatch.setattr(service, "prepare_html", recording_prepare_html)
    monkeypatch.setattr(service.markdown, "markdown", recording_markdown)

    await preparer.prepare_html("<p>hello</p>")
    await preparer.prepare_markdown("# Title")

    assert parser_threads and markdown_threads
    assert all(
        thread != event_loop_thread for thread in (*parser_threads, *markdown_threads)
    )


async def test_prepare_markdown_translates_invalid_generated_urls(
    preparer: DefaultHtmlPreparer,
) -> None:
    with pytest.raises(PreparationError, match="Invalid HTML preparation input"):
        await preparer.prepare_markdown("![](http://[)")


async def test_prepare_markdown_translates_invalid_base_paths(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path_type = type(tmp_path)
    original_expanduser = path_type.expanduser

    def expanduser(path: Path) -> Path:
        if str(path) == "broken-base":
            raise RuntimeError("home directory is unavailable")
        return original_expanduser(path)

    monkeypatch.setattr(path_type, "expanduser", expanduser)

    with pytest.raises(ResourceResolutionError, match="normalize local resource path"):
        await preparer.prepare_markdown("# Title", markdown_path="broken-base")


async def test_prepare_markdown_requires_content_or_path(
    preparer: DefaultHtmlPreparer,
) -> None:
    with pytest.raises(InvalidRenderRequest, match="markdown"):
        await preparer.prepare_markdown()


async def test_prepare_template_requires_name(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
) -> None:
    with pytest.raises(InvalidRenderRequest, match="template_name"):
        await preparer.prepare_template(tmp_path, "", {})


async def test_prepare_template_translates_template_engine_errors(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
) -> None:
    with pytest.raises(PreparationError, match="Template rendering failed"):
        await preparer.prepare_template(tmp_path, "missing.html", {})


async def test_prepare_template_keeps_directory_base_and_filters(
    tmp_path: Path,
    preparer: DefaultHtmlPreparer,
) -> None:
    (tmp_path / "card.html").write_text(
        "<strong>{{ name|caps }}</strong>",
        encoding="utf-8",
    )
    prepared = await preparer.prepare_template(
        tmp_path,
        "card.html",
        {"name": "takumi"},
        filters={"caps": str.upper},
    )
    assert prepared.html == "<strong>TAKUMI</strong>"
    assert (
        prepared.document_base.preparation_base_url == f"{tmp_path.resolve().as_uri()}/"  # noqa: ASYNC240
    )
