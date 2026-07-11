"""Preparation service boundary consumed by the rendering application.

``HtmlPreparer`` is the injectable seam: application use cases depend on the
protocol, while ``DefaultHtmlPreparer`` delegates to the module-level
preparation pipeline. Resource readers and access policies become injected
dependencies of the concrete preparer in the resource-DI migration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, final

from nonebot_plugin_htmlrender.resources.templating import (
    render_template_html as _render_template_html,
)

from .content import prepare_markdown as _prepare_markdown
from .content import prepare_template as _prepare_template
from .content import prepare_text as _prepare_text
from .html import prepare_html as _prepare_html

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from nonebot_plugin_htmlrender.resources.templating import (
        ExtensionSpec,
        FilterCallable,
    )

    from .models import PreparedHtml


class HtmlPreparer(Protocol):
    """Prepares neutral content sources into the shared ``PreparedHtml`` IR."""

    async def prepare_html(
        self,
        html: str,
        *,
        base_url: str | None = None,
    ) -> PreparedHtml: ...

    async def prepare_text(
        self,
        text: str,
        *,
        css_path: str = "",
    ) -> PreparedHtml: ...

    async def prepare_markdown(
        self,
        markdown_text: str = "",
        *,
        markdown_path: str = "",
        css_path: str = "",
        resource_strict: bool | None = None,
    ) -> PreparedHtml: ...

    async def prepare_template(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
    ) -> PreparedHtml: ...

    async def render_template_html(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
    ) -> str: ...


@final
class DefaultHtmlPreparer:
    """Preparer backed by the module-level preparation pipeline."""

    async def prepare_html(
        self,
        html: str,
        *,
        base_url: str | None = None,
    ) -> PreparedHtml:
        return _prepare_html(html, base_url=base_url)

    async def prepare_text(
        self,
        text: str,
        *,
        css_path: str = "",
    ) -> PreparedHtml:
        return await _prepare_text(text, css_path=css_path)

    async def prepare_markdown(
        self,
        markdown_text: str = "",
        *,
        markdown_path: str = "",
        css_path: str = "",
        resource_strict: bool | None = None,
    ) -> PreparedHtml:
        return await _prepare_markdown(
            markdown_text,
            markdown_path=markdown_path,
            css_path=css_path,
            resource_strict=resource_strict,
        )

    async def prepare_template(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
    ) -> PreparedHtml:
        return await _prepare_template(
            template_path,
            template_name,
            variables,
            filters=filters,
            extensions=extensions,
        )

    async def render_template_html(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
    ) -> str:
        return await _render_template_html(
            template_path,
            template_name,
            variables,
            filters=filters,
            extensions=extensions,
        )
