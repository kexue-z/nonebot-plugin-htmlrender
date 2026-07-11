from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nonebot_plugin_htmlrender.application import build_application
from nonebot_plugin_htmlrender.preparation.service import DefaultHtmlPreparer
from nonebot_plugin_htmlrender.providers.sdk import EngineBindings
from nonebot_plugin_htmlrender.rendering import (
    CapabilityCatalog,
    CapabilityKey,
    RenderHtmlRequest,
    ResourcePolicy,
)

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        RasterOptions,
    )


@dataclass
class _FakeLifecycle:
    startup_calls: int = 0

    async def startup(self) -> None:
        self.startup_calls += 1

    async def probe(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


@dataclass
class _FakeExecutor:
    calls: list[tuple[PreparedHtml, RasterOptions]] = field(default_factory=list)

    async def execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resource_policy: ResourcePolicy | None = None,
        timeout_seconds: float | None = None,
    ) -> bytes:
        del resource_policy, timeout_seconds
        self.calls.append((prepared, options))
        return b"image-bytes"


class _Marker:
    pass


def test_build_application_with_executor_binds_all_use_cases() -> None:
    marker = _Marker()
    key = CapabilityKey("test.marker", _Marker)
    engine = EngineBindings(
        lifecycle=_FakeLifecycle(),
        prepared_html_executor=_FakeExecutor(),
        provider_capabilities=CapabilityCatalog().with_capability(key, marker),
    )

    application = build_application(engine=engine)

    assert application.renderer.capabilities == frozenset(
        {
            "render_html",
            "render_text",
            "render_markdown",
            "render_template",
            "render_template_html",
            "rasterize_html",
        }
    )
    assert application.capabilities.require(key) is marker


def test_build_application_without_executor_only_renders_html() -> None:
    engine = EngineBindings(lifecycle=_FakeLifecycle())

    application = build_application(engine=engine)

    assert application.renderer.capabilities == frozenset({"render_template_html"})


async def test_built_application_renders_through_real_preparer() -> None:
    executor = _FakeExecutor()
    engine = EngineBindings(
        lifecycle=_FakeLifecycle(),
        prepared_html_executor=executor,
    )
    application = build_application(
        engine=engine,
        preparer=DefaultHtmlPreparer(),
    )

    artifact = await application.renderer.render_html(
        RenderHtmlRequest(html="<p>hello</p>")
    )

    assert bytes(artifact) == b"image-bytes"
    assert artifact.format == "png"
    prepared, options = executor.calls[0]
    assert "<p>hello</p>" in prepared.html
    assert options.width == 800
