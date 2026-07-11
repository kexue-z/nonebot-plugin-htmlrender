"""Shared text, Markdown, and Jinja preparation pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
from anyio.to_thread import run_sync
import markdown

from nonebot_plugin_htmlrender.resources import (
    PackageResourceSource,
    read_resource_text,
)
from nonebot_plugin_htmlrender.resources.templating import (
    FilterCallable,
    render_template_html,
)

from .html import prepare_html
from .materialize import materialize_local_assets
from .models import PreparedStylesheet
from .template_assets import stage_template_variables

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .models import PreparedHtml

BUILTIN_TEMPLATES = PackageResourceSource(
    "nonebot_plugin_htmlrender",
    "templates",
)
TEXT_TEMPLATES = PackageResourceSource(
    "nonebot_plugin_htmlrender",
    "templates/text",
)
MARKDOWN_TEMPLATES = PackageResourceSource(
    "nonebot_plugin_htmlrender",
    "templates/markdown",
)


async def _read_builtin(path: str) -> str:
    return await read_resource_text(BUILTIN_TEMPLATES.resource(path))


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
        TEXT_TEMPLATES,
        "text.html",
        {"text": text, "css": ""},
        immutable=True,
    )
    stylesheet_base = await run_sync(_path_uri, css_path) if css_path else None
    return prepare_html(
        html,
        stylesheets=(PreparedStylesheet(css=css, base_url=stylesheet_base),),
    )


async def prepare_markdown(
    markdown_text: str = "",
    *,
    markdown_path: str = "",
    css_path: str = "",
    resource_strict: bool | None = None,
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
        MARKDOWN_TEMPLATES,
        "markdown.html",
        {"md": rendered_markdown, "css": "", "extra": extra},
        immutable=True,
    )
    markup_base = await run_sync(_path_uri, markdown_path) if markdown_path else None
    stylesheet_base = await run_sync(_path_uri, css_path) if css_path else None
    prepared = prepare_html(
        html,
        base_url=markup_base,
        stylesheets=(PreparedStylesheet(css=css, base_url=stylesheet_base),),
    )
    if resource_strict is None:
        return prepared
    return await materialize_local_assets(prepared, strict=resource_strict)


async def prepare_template(
    template_path: str | Path,
    template_name: str,
    variables: Mapping[str, Any],
    *,
    filters: Mapping[str, FilterCallable] | None = None,
) -> PreparedHtml:
    staged_variables, assets = await stage_template_variables(
        variables,
        template_base=template_path,
    )
    html = await render_template_html(
        template_path,
        template_name,
        staged_variables,
        filters=filters,
    )
    return prepare_html(
        html,
        base_url=await run_sync(_directory_uri, template_path),
        assets=assets,
    )


__all__ = (
    "prepare_markdown",
    "prepare_template",
    "prepare_text",
)
