from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio
import pytest

from nonebot_plugin_htmlrender.application import (
    RasterizeHtml,
    Renderer,
    RendererBindings,
    RenderHtml,
    RenderMarkdown,
    RenderTemplate,
    RenderTemplateHtml,
    RenderText,
)
from nonebot_plugin_htmlrender.preparation import prepare_html
from nonebot_plugin_htmlrender.preparation.models import PreparedHtml, RasterOptions
from nonebot_plugin_htmlrender.rendering import (
    CapabilityUnavailable,
    OperationAdmissionGate,
    ProviderExecutionError,
    RasterizeHtmlRequest,
    RenderedImage,
    RenderHtmlRequest,
    RenderMarkdownRequest,
    RenderTemplateHtmlRequest,
    RenderTemplateRequest,
    RenderTextRequest,
    ResourcePolicy,
)
from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode
from tests.image_fixtures import rendered_image

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from nonebot_plugin_htmlrender.resources.templating import (
        ExtensionSpec,
        FilterCallable,
    )

PREPARED = prepare_html("<p>prepared</p>")


@dataclass
class _ExecutorCall:
    prepared: PreparedHtml
    options: RasterOptions
    resource_policy: ResourcePolicy | None
    timeout_seconds: float | None


@dataclass
class _FakeExecutor:
    result: RenderedImage = field(
        default_factory=lambda: rendered_image("png", width=1600, height=713)
    )
    calls: list[_ExecutorCall] = field(default_factory=list)

    async def execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resource_policy: ResourcePolicy | None = None,
        timeout_seconds: float | None = None,
    ) -> RenderedImage:
        self.calls.append(
            _ExecutorCall(prepared, options, resource_policy, timeout_seconds)
        )
        return self.result


@dataclass
class _FakePreparer:
    prepared: PreparedHtml = PREPARED
    html_content: str = "<p>template html</p>"
    prepare_calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    prepare_delay: float = 0

    async def prepare_html(
        self,
        html: str,
        *,
        base_url: str | None = None,
    ) -> PreparedHtml:
        if self.prepare_delay:
            await anyio.sleep(self.prepare_delay)
        self.prepare_calls.append(("html", {"html": html, "base_url": base_url}))
        return self.prepared

    async def prepare_text(
        self,
        text: str,
        *,
        css_path: str = "",
    ) -> PreparedHtml:
        self.prepare_calls.append(("text", {"text": text, "css_path": css_path}))
        return self.prepared

    async def prepare_markdown(
        self,
        markdown_text: str = "",
        *,
        markdown_path: str = "",
        css_path: str = "",
        resource_mode: ResourceResolveMode | None = None,
    ) -> PreparedHtml:
        self.prepare_calls.append(
            (
                "markdown",
                {
                    "markdown_text": markdown_text,
                    "markdown_path": markdown_path,
                    "css_path": css_path,
                    "resource_mode": resource_mode,
                },
            )
        )
        return self.prepared

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
        self.prepare_calls.append(
            (
                "template",
                {
                    "template_path": template_path,
                    "template_name": template_name,
                    "variables": dict(variables),
                    "filters": filters,
                    "extensions": tuple(extensions),
                    "resource_mode": resource_mode,
                },
            )
        )
        return self.prepared

    async def render_template_html(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
    ) -> str:
        self.prepare_calls.append(
            (
                "template_html",
                {
                    "template_path": template_path,
                    "template_name": template_name,
                    "variables": dict(variables),
                    "filters": filters,
                    "extensions": tuple(extensions),
                },
            )
        )
        return self.html_content


def _full_renderer(
    result: RenderedImage | None = None,
) -> tuple[Renderer, _FakePreparer, _FakeExecutor]:
    preparer = _FakePreparer()
    executor = _FakeExecutor() if result is None else _FakeExecutor(result=result)
    bindings = RendererBindings(
        render_html=RenderHtml(preparer=preparer, executor=executor),
        render_text=RenderText(preparer=preparer, executor=executor),
        render_markdown=RenderMarkdown(preparer=preparer, executor=executor),
        render_template=RenderTemplate(preparer=preparer, executor=executor),
        render_template_html=RenderTemplateHtml(preparer=preparer),
        rasterize_html=RasterizeHtml(executor=executor),
    )
    return (
        Renderer(
            bindings,
            operation_admission=OperationAdmissionGate(),
        ),
        preparer,
        executor,
    )


async def test_render_html_returns_typed_artifact() -> None:
    expected = rendered_image("jpeg", width=1280, height=960)
    renderer, preparer, executor = _full_renderer(expected)
    request = RenderHtmlRequest(
        html="<p>hi</p>",
        raster=RasterOptions(width=640, height=480, format="jpeg", quality=80),
        base_url="https://example.invalid/",
        resource_policy=ResourcePolicy.STRICT,
        timeout_seconds=2.5,
    )

    artifact = await renderer.render_html(request)

    assert artifact is expected
    assert artifact.format == "jpeg"
    assert artifact.width == 1280
    assert artifact.height == 960
    assert preparer.prepare_calls == [
        ("html", {"html": "<p>hi</p>", "base_url": "https://example.invalid/"})
    ]
    call = executor.calls[0]
    assert call.prepared is PREPARED
    assert call.options.width == 640
    assert call.resource_policy is ResourcePolicy.STRICT
    assert call.timeout_seconds == 2.5


async def test_render_timeout_includes_preparation() -> None:
    renderer, preparer, executor = _full_renderer()
    preparer.prepare_delay = 0.1

    with pytest.raises(ProviderExecutionError, match="timed out"):
        await renderer.render_html(
            RenderHtmlRequest(html="<p>slow</p>", timeout_seconds=0.01)
        )

    assert executor.calls == []


async def test_render_text_flows_through_executor() -> None:
    renderer, preparer, executor = _full_renderer()

    artifact = await renderer.render_text(
        RenderTextRequest(
            text="hello",
            css_path="style.css",
            resource_policy=ResourcePolicy.STRICT,
        )
    )

    assert artifact.format == "png"
    assert artifact.width == 1600
    assert artifact.height == 713
    assert preparer.prepare_calls == [
        ("text", {"text": "hello", "css_path": "style.css"})
    ]
    assert executor.calls[0].resource_policy is ResourcePolicy.STRICT


@pytest.mark.parametrize(
    ("policy", "expected_mode"),
    [
        (None, None),
        (ResourcePolicy.OFF, ResourceResolveMode.OFF),
        (ResourcePolicy.AUTO, ResourceResolveMode.AUTO),
        (ResourcePolicy.STRICT, ResourceResolveMode.STRICT),
    ],
)
async def test_render_markdown_maps_policy_to_preparation_mode(
    policy: ResourcePolicy | None,
    expected_mode: ResourceResolveMode | None,
) -> None:
    renderer, preparer, executor = _full_renderer()

    await renderer.render_markdown(
        RenderMarkdownRequest(markdown="# title", resource_policy=policy)
    )

    kind, arguments = preparer.prepare_calls[0]
    assert kind == "markdown"
    assert arguments["resource_mode"] == expected_mode
    assert executor.calls[0].resource_policy is policy


@pytest.mark.parametrize(
    ("policy", "expected_mode"),
    [
        (None, None),
        (ResourcePolicy.OFF, ResourceResolveMode.OFF),
        (ResourcePolicy.AUTO, ResourceResolveMode.AUTO),
        (ResourcePolicy.STRICT, ResourceResolveMode.STRICT),
    ],
)
async def test_render_template_maps_policy_to_preparation_mode(
    policy: ResourcePolicy | None,
    expected_mode: ResourceResolveMode | None,
) -> None:
    renderer, preparer, executor = _full_renderer()

    await renderer.render_template(
        RenderTemplateRequest(
            template_path="templates",
            template_name="page.html",
            variables={"title": "hi"},
            resource_policy=policy,
        )
    )

    kind, arguments = preparer.prepare_calls[0]
    assert kind == "template"
    assert arguments["resource_mode"] is expected_mode
    assert executor.calls[0].resource_policy is policy


async def test_render_template_and_template_html() -> None:
    renderer, preparer, executor = _full_renderer()

    image = await renderer.render_template(
        RenderTemplateRequest(
            template_path="templates",
            template_name="page.html",
            variables={"title": "hi"},
        )
    )
    html = await renderer.render_template_html(
        RenderTemplateHtmlRequest(
            template_path="templates",
            template_name="page.html",
            variables={"title": "hi"},
        )
    )

    assert image is executor.result
    assert str(html) == "<p>template html</p>"
    kinds = [kind for kind, _ in preparer.prepare_calls]
    assert kinds == ["template", "template_html"]


async def test_rasterize_html_passes_prepared_through() -> None:
    renderer, _, executor = _full_renderer()
    prepared = prepare_html("<p>direct</p>")

    artifact = await renderer.rasterize_html(
        RasterizeHtmlRequest(prepared=prepared, options=RasterOptions(width=320))
    )

    assert artifact.width == 1600
    assert artifact.height == 713
    assert executor.calls[0].prepared is prepared


async def test_missing_binding_raises_capability_unavailable() -> None:
    renderer = Renderer(
        RendererBindings(),
        operation_admission=OperationAdmissionGate(),
    )

    assert renderer.supported_commands == frozenset()
    assert not renderer.supports("render_html")
    with pytest.raises(CapabilityUnavailable) as exc_info:
        await renderer.render_html(RenderHtmlRequest(html="<p>hi</p>"))
    assert exc_info.value.capability == "render_html"


def test_capabilities_derived_from_bindings() -> None:
    preparer = _FakePreparer()
    executor = _FakeExecutor()
    renderer = Renderer(
        RendererBindings(
            render_text=RenderText(preparer=preparer, executor=executor),
            rasterize_html=RasterizeHtml(executor=executor),
        ),
        operation_admission=OperationAdmissionGate(),
    )

    assert renderer.supported_commands == frozenset({"render_text", "rasterize_html"})
    assert renderer.supports("rasterize_html")
    assert not renderer.supports("render_markdown")
