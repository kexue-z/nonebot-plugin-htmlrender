from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, final

import markdown

from nonebot_plugin_htmlrender.errors import InvalidRenderRequest
from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode
from nonebot_plugin_htmlrender.resources.models import PackageResourceRef
from nonebot_plugin_htmlrender.resources.source import PackageResourceSource

from .html import prepare_html
from .materialize import materialize_local_assets
from .models import PreparedHtml, PreparedStylesheet
from .template_assets import stage_template_variables

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nonebot_plugin_htmlrender.resources.ports import (
        TemplateCompiler,
        WorkerExecutor,
    )
    from nonebot_plugin_htmlrender.resources.service import ResourceService
    from nonebot_plugin_htmlrender.resources.templating import (
        ExtensionSpec,
        FilterCallable,
    )

BUILTIN_TEMPLATES = PackageResourceSource("nonebot_plugin_htmlrender", "templates")
TEXT_TEMPLATES = PackageResourceSource("nonebot_plugin_htmlrender", "templates/text")
MARKDOWN_TEMPLATES = PackageResourceSource(
    "nonebot_plugin_htmlrender",
    "templates/markdown",
)


class HtmlPreparer(Protocol):
    async def prepare_html(
        self, html: str, *, base_url: str | None = None
    ) -> PreparedHtml: ...

    async def prepare_text(self, text: str, *, css_path: str = "") -> PreparedHtml: ...

    async def prepare_markdown(
        self,
        markdown_text: str = "",
        *,
        markdown_path: str = "",
        css_path: str = "",
        resource_mode: ResourceResolveMode | None = None,
    ) -> PreparedHtml: ...

    async def prepare_template(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
        resource_mode: ResourceResolveMode | None = None,
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
    """Fully injected preparation pipeline owned by one Application."""

    def __init__(
        self,
        *,
        resources: ResourceService,
        templates: TemplateCompiler,
        worker: WorkerExecutor,
    ) -> None:
        self._resources = resources
        self._templates = templates
        self._worker = worker

    def _path_uri(self, path: str | Path, *, directory: bool = False) -> str:
        uri = self._resources.authorize_local(Path(path)).as_uri()
        return f"{uri.rstrip('/')}/" if directory else uri

    async def _builtin(self, name: str) -> str:
        return await self._resources.read_text(
            PackageResourceRef(
                BUILTIN_TEMPLATES.package, f"{BUILTIN_TEMPLATES.root}/{name}"
            )
        )

    async def prepare_html(
        self, html: str, *, base_url: str | None = None
    ) -> PreparedHtml:
        return await self._worker.run_sync(prepare_html, html, base_url=base_url)

    async def prepare_text(self, text: str, *, css_path: str = "") -> PreparedHtml:
        css = (
            await self._resources.read_text(css_path)
            if css_path
            else await self._builtin("text/text.css")
        )
        html = await self._templates.render(
            TEXT_TEMPLATES,
            "text.html",
            {"text": text, "css": ""},
            immutable=True,
        )
        stylesheet_base = (
            await self._worker.run_sync(self._path_uri, css_path) if css_path else None
        )
        return await self._worker.run_sync(
            prepare_html,
            html,
            stylesheets=(PreparedStylesheet(css=css, base_url=stylesheet_base),),
        )

    async def prepare_markdown(
        self,
        markdown_text: str = "",
        *,
        markdown_path: str = "",
        css_path: str = "",
        resource_mode: ResourceResolveMode | None = None,
    ) -> PreparedHtml:
        if not markdown_text:
            if not markdown_path:
                raise InvalidRenderRequest("markdown or markdown_path must be provided")
            markdown_text = await self._resources.read_text(markdown_path)
        rendered = await self._worker.run_sync(
            markdown.markdown,
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
        if "math/tex" in rendered:
            katex_css = await self._builtin("markdown/katex/katex.min.b64_fonts.css")
            katex_js = await self._builtin("markdown/katex/katex.min.js")
            mhchem_js = await self._builtin("markdown/katex/mhchem.min.js")
            mathtex_js = await self._builtin(
                "markdown/katex/mathtex-script-type.min.js"
            )
            extra = (
                f'<style type="text/css">{katex_css}</style>'
                f"<script defer>{katex_js}</script>"
                f"<script defer>{mhchem_js}</script>"
                f"<script defer>{mathtex_js}</script>"
            )
        css = (
            await self._resources.read_text(css_path)
            if css_path
            else await self._builtin("markdown/github-markdown-light.css")
            + await self._builtin("markdown/pygments-default.css")
        )
        html = await self._templates.render(
            MARKDOWN_TEMPLATES,
            "markdown.html",
            {"md": rendered, "css": "", "extra": extra},
            immutable=True,
        )
        markup_base = (
            await self._worker.run_sync(self._path_uri, markdown_path)
            if markdown_path
            else None
        )
        stylesheet_base = (
            await self._worker.run_sync(self._path_uri, css_path) if css_path else None
        )
        prepared = await self._worker.run_sync(
            prepare_html,
            html,
            base_url=markup_base,
            stylesheets=(PreparedStylesheet(css=css, base_url=stylesheet_base),),
        )
        effective_mode = resource_mode or self._resources.strategy.resolve_mode
        if effective_mode is ResourceResolveMode.OFF:
            return prepared
        return await materialize_local_assets(
            prepared,
            resources=self._resources,
            strict=effective_mode is ResourceResolveMode.STRICT,
        )

    async def prepare_template(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
        resource_mode: ResourceResolveMode | None = None,
    ) -> PreparedHtml:
        if not template_name:
            raise InvalidRenderRequest("template_name must not be empty")
        template_root = await self._worker.run_sync(
            self._resources.authorize_local,
            Path(template_path),
        )
        effective_mode = resource_mode or self._resources.strategy.resolve_mode
        if effective_mode is ResourceResolveMode.OFF:
            staged, assets = dict(variables), ()
        else:
            staged, assets = await stage_template_variables(
                variables,
                template_base=template_root,
                resources=self._resources,
                strict=effective_mode is ResourceResolveMode.STRICT,
            )
        html = await self._templates.render(
            template_root,
            template_name,
            staged,
            filters=filters,
            extensions=extensions,
        )
        base = await self._worker.run_sync(
            self._path_uri,
            template_root,
            directory=True,
        )
        return await self._worker.run_sync(
            prepare_html,
            html,
            base_url=base,
            assets=assets,
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
        if not template_name:
            raise InvalidRenderRequest("template_name must not be empty")
        template_root = await self._worker.run_sync(
            self._resources.authorize_local,
            Path(template_path),
        )
        return await self._templates.render(
            template_root,
            template_name,
            variables,
            filters=filters,
            extensions=extensions,
        )


__all__ = ["DefaultHtmlPreparer", "HtmlPreparer"]
