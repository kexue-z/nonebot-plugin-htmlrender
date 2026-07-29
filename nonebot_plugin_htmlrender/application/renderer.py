"""Public renderer facade over the injected use-case bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, final

from nonebot_plugin_htmlrender.rendering.errors import CapabilityUnavailable

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.rendering.admission import OperationAdmissionGate
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

    def __init__(
        self,
        bindings: RendererBindings,
        *,
        operation_admission: OperationAdmissionGate,
    ) -> None:
        self._bindings = bindings
        self._operation_admission = operation_admission

    @property
    def supported_commands(self) -> frozenset[str]:
        """Render command names derived from the bound use cases."""
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
        async with self._operation_admission.operation():
            return await use_case.execute(request)

    async def render_text(self, request: RenderTextRequest) -> RenderedImage:
        use_case = self._require(self._bindings.render_text, "render_text")
        async with self._operation_admission.operation():
            return await use_case.execute(request)

    async def render_markdown(self, request: RenderMarkdownRequest) -> RenderedImage:
        use_case = self._require(self._bindings.render_markdown, "render_markdown")
        async with self._operation_admission.operation():
            return await use_case.execute(request)

    async def render_template(self, request: RenderTemplateRequest) -> RenderedImage:
        use_case = self._require(self._bindings.render_template, "render_template")
        async with self._operation_admission.operation():
            return await use_case.execute(request)

    async def render_template_html(
        self,
        request: RenderTemplateHtmlRequest,
    ) -> RenderedHtml:
        use_case = self._require(
            self._bindings.render_template_html,
            "render_template_html",
        )
        async with self._operation_admission.operation():
            return await use_case.execute(request)

    async def rasterize_html(self, request: RasterizeHtmlRequest) -> RenderedImage:
        use_case = self._require(self._bindings.rasterize_html, "rasterize_html")
        async with self._operation_admission.operation():
            return await use_case.execute(request)
