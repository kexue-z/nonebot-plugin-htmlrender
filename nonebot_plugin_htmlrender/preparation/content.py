"""Shared text, Markdown, and Jinja preparation pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
from anyio.to_thread import run_sync
import markdown

from nonebot_plugin_htmlrender.resources import FileCachePolicy, read_resource_text
from nonebot_plugin_htmlrender.resources.templating import (
    FilterCallable,
    render_template_html,
)

from .html import prepare_html

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .models import PreparedHtml

TEMPLATES_PATH = Path(__file__).resolve().parents[1] / "templates"
TEXT_TEMPLATES_PATH = TEMPLATES_PATH / "text"
MARKDOWN_TEMPLATES_PATH = TEMPLATES_PATH / "markdown"
TEXT_TEMPLATE_FILE = TEXT_TEMPLATES_PATH / "text.html"
MARKDOWN_TEMPLATE_FILE = MARKDOWN_TEMPLATES_PATH / "markdown.html"


async def _read_builtin(path: str) -> str:
    return await read_resource_text(
        TEMPLATES_PATH / path,
        policy=FileCachePolicy.IMMUTABLE,
    )


async def _read_builtins(*paths: str) -> tuple[str, ...]:
    contents = [""] * len(paths)

    async def read_one(index: int, path: str) -> None:
        contents[index] = await _read_builtin(path)

    async with anyio.create_task_group() as task_group:
        for index, path in enumerate(paths):
            task_group.start_soon(read_one, index, path)
    return tuple(contents)


def _path_uri(path: str | Path) -> str:
    return Path(path).expanduser().resolve().as_uri()


def _directory_uri(path: str | Path) -> str:
    return f"{_path_uri(path).rstrip('/')}/"


async def prepare_text(
    text: str,
    *,
    css_path: str = "",
) -> PreparedHtml:
    css = (
        await read_resource_text(css_path)
        if css_path
        else await _read_builtin("text/text.css")
    )
    html = await render_template_html(
        TEXT_TEMPLATES_PATH,
        TEXT_TEMPLATE_FILE.name,
        {"text": text, "css": css},
        immutable=True,
    )
    base_url = (
        await run_sync(_path_uri, css_path) if css_path else TEXT_TEMPLATE_FILE.as_uri()
    )
    return prepare_html(html, base_url=base_url)


async def prepare_markdown(
    markdown_text: str = "",
    *,
    markdown_path: str = "",
    css_path: str = "",
) -> PreparedHtml:
    if not markdown_text:
        if not markdown_path:
            raise ValueError("md or md_path must be provided")
        markdown_text = await read_resource_text(markdown_path)

    rendered_markdown = markdown.markdown(
        markdown_text,
        extensions=[
            "pymdownx.tasklist",
            "tables",
            "fenced_code",
            "codehilite",
            "mdx_math",
            "pymdownx.tilde",
        ],
        extension_configs={"mdx_math": {"enable_dollar_delimiter": True}},
    )

    extra = ""
    if "math/tex" in rendered_markdown:
        katex_css, katex_js, mhchem_js, mathtex_js = await _read_builtins(
            "markdown/katex/katex.min.b64_fonts.css",
            "markdown/katex/katex.min.js",
            "markdown/katex/mhchem.min.js",
            "markdown/katex/mathtex-script-type.min.js",
        )
        extra = (
            f'<style type="text/css">{katex_css}</style>'
            f"<script defer>{katex_js}</script>"
            f"<script defer>{mhchem_js}</script>"
            f"<script defer>{mathtex_js}</script>"
        )

    if css_path:
        css = await read_resource_text(css_path)
    else:
        github_css, pygments_css = await _read_builtins(
            "markdown/github-markdown-light.css",
            "markdown/pygments-default.css",
        )
        css = github_css + pygments_css

    html = await render_template_html(
        MARKDOWN_TEMPLATES_PATH,
        MARKDOWN_TEMPLATE_FILE.name,
        {"md": rendered_markdown, "css": css, "extra": extra},
        immutable=True,
    )
    base_url = (
        await run_sync(_path_uri, css_path)
        if css_path
        else MARKDOWN_TEMPLATE_FILE.as_uri()
    )
    return prepare_html(html, base_url=base_url)


async def prepare_template(
    template_path: str | Path,
    template_name: str,
    variables: Mapping[str, Any],
    *,
    filters: Mapping[str, FilterCallable] | None = None,
) -> PreparedHtml:
    html = await render_template_html(
        template_path,
        template_name,
        variables,
        filters=filters,
    )
    return prepare_html(html, base_url=await run_sync(_directory_uri, template_path))


__all__ = (
    "MARKDOWN_TEMPLATES_PATH",
    "MARKDOWN_TEMPLATE_FILE",
    "TEMPLATES_PATH",
    "TEXT_TEMPLATES_PATH",
    "TEXT_TEMPLATE_FILE",
    "prepare_markdown",
    "prepare_template",
    "prepare_text",
)
