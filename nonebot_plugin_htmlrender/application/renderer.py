"""Public renderer facade over the injected use-case bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, final

from nonebot_plugin_htmlrender.rendering.errors import CapabilityUnavailable

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.rendering.artifacts import (
        RenderedHtml,
        RenderedImage,
    )
    from nonebot_plugin_htmlrender.rendering.requests import (
        RasterizeHtmlRequest,
        RenderHtmlRequest,
        RenderMarkdownRequest,
        RenderTemplateHtmlRequest,
        RenderTemplateRequest,
        RenderTextRequest,
    )

    from .bindings import RendererBindings

_BindingT = TypeVar("_BindingT")


@final
class Renderer:
    """Executes render commands through explicitly injected use cases."""

    def __init__(self, bindings: RendererBindings) -> None:
        self._bindings = bindings

    @property
    def capabilities(self) -> frozenset[str]:
        """Capability names derived from the bound use cases."""
        return self._bindings.present()

    def supports(self, capability: str) -> bool:
        return capability in self._bindings.present()

    @staticmethod
    def _require(binding: _BindingT | None, capability: str) -> _BindingT:
        if binding is None:
            raise CapabilityUnavailable(capability)
        return binding

    async def render_html(self, request: RenderHtmlRequest) -> RenderedImage:
        use_case = self._require(self._bindings.render_html, "render_html")
        return await use_case.execute(request)

    async def render_text(self, request: RenderTextRequest) -> RenderedImage:
        use_case = self._require(self._bindings.render_text, "render_text")
        return await use_case.execute(request)

    async def render_markdown(self, request: RenderMarkdownRequest) -> RenderedImage:
        use_case = self._require(self._bindings.render_markdown, "render_markdown")
        return await use_case.execute(request)

    async def render_template(self, request: RenderTemplateRequest) -> RenderedImage:
        use_case = self._require(self._bindings.render_template, "render_template")
        return await use_case.execute(request)

    async def render_template_html(
        self,
        request: RenderTemplateHtmlRequest,
    ) -> RenderedHtml:
        use_case = self._require(
            self._bindings.render_template_html,
            "render_template_html",
        )
        return await use_case.execute(request)

    async def rasterize_html(self, request: RasterizeHtmlRequest) -> RenderedImage:
        use_case = self._require(self._bindings.rasterize_html, "rasterize_html")
        return await use_case.execute(request)
