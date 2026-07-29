from __future__ import annotations

from dataclasses import dataclass, field
from inspect import signature
import math
from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender import api
from nonebot_plugin_htmlrender.adapters.resources import (
    AnyioWorkerExecutor,
    ConfiguredLocalAccessPolicy,
    RemoteTransportExecutor,
    build_resource_reader,
)
from nonebot_plugin_htmlrender.adapters.templates import JinjaTemplateCompiler
from nonebot_plugin_htmlrender.api._default import (
    set_default_application,
    set_default_application_factory,
)
from nonebot_plugin_htmlrender.application import build_application
from nonebot_plugin_htmlrender.bootstrap.composition import prepare_runtime
from nonebot_plugin_htmlrender.bootstrap.settings import RenderSettings
from nonebot_plugin_htmlrender.preparation import prepare_html
from nonebot_plugin_htmlrender.preparation.models import PreparedHtml, RasterOptions
from nonebot_plugin_htmlrender.preparation.service import DefaultHtmlPreparer
from nonebot_plugin_htmlrender.providers.sdk import EngineBindings
from nonebot_plugin_htmlrender.rendering import (
    ApplicationNotInitialized,
    CapabilityUnavailable,
    InvalidRenderRequest,
    RenderedImage,
    ResourcePolicy,
)
from nonebot_plugin_htmlrender.resources.config import (
    ResourceCacheSettings,
    ResourceStrategy,
)
from nonebot_plugin_htmlrender.resources.observation import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.service import ResourceService
from tests.image_fixtures import rendered_image

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Literal


@dataclass
class _FakeLifecycle:
    async def startup(self) -> None:
        return None

    async def probe(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


@dataclass
class _ExecutorCall:
    prepared: PreparedHtml
    options: RasterOptions
    resource_policy: ResourcePolicy | None
    timeout_seconds: float | None


@dataclass
class _FakeExecutor:
    calls: list[_ExecutorCall] = field(default_factory=list)
    results: list[RenderedImage] = field(default_factory=list)

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
        result = rendered_image(
            options.format,
            width=math.ceil(options.width * options.device_pixel_ratio),
            height=(
                713
                if options.height is None
                else math.ceil(options.height * options.device_pixel_ratio)
            ),
        )
        self.results.append(result)
        return result


@pytest.fixture
def default_executor() -> Iterator[_FakeExecutor]:
    executor = _FakeExecutor()
    observer = NoopCacheObserver()
    worker = AnyioWorkerExecutor()
    local_access = ConfiguredLocalAccessPolicy(
        allowed_roots=(),
        allow_any=True,
    )
    resources = ResourceService(
        reader=build_resource_reader(
            ResourceCacheSettings(),
            observer,
            worker,
            remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
        ),
        local_access=local_access,
        strategy=ResourceStrategy(),
    )
    preparer = DefaultHtmlPreparer(
        resources=resources,
        templates=JinjaTemplateCompiler(
            max_entries=8,
            observer=observer,
            worker=worker,
            local_access=local_access,
        ),
        worker=worker,
    )
    application = build_application(
        engine=EngineBindings(
            lifecycle=_FakeLifecycle(),
            prepared_html_executor=executor,
        ),
        preparer=preparer,
        resources=resources,
    )
    previous = set_default_application(application)
    yield executor
    set_default_application(previous)


def test_default_accessors_require_initialization() -> None:
    previous_application = set_default_application(None)
    previous_factory = set_default_application_factory(None)
    try:
        with pytest.raises(ApplicationNotInitialized, match="not initialized"):
            api.get_default_application()
        with pytest.raises(ApplicationNotInitialized, match="not initialized"):
            api.get_default_renderer()
    finally:
        set_default_application(previous_application)
        set_default_application_factory(previous_factory)


async def test_default_factory_builds_provider_free_application(
    tmp_path: Path,
) -> None:
    settings = RenderSettings.model_validate(
        {
            "resources": {
                "local_access": {
                    "allowed_paths": [tmp_path],
                }
            }
        }
    )
    runtime = prepare_runtime(settings)
    previous_application = set_default_application(None)
    previous_factory = set_default_application_factory(runtime.build_application)
    application = None
    try:
        application = api.get_default_application()

        assert application is api.get_default_application()
        assert application.renderer.supported_commands == frozenset(
            {"render_template_html"}
        )

        (tmp_path / "page.html").write_text(
            "<h1>{{ title }}</h1>",
            encoding="utf-8",
        )
        rendered = await api.render_template_html(
            tmp_path,
            "page.html",
            {"title": "Provider-free"},
        )

        assert "<h1>Provider-free</h1>" in str(rendered)
        with pytest.raises(CapabilityUnavailable, match="render_html"):
            await api.render_html("<p>requires a provider</p>")
    finally:
        if application is not None:
            await application.aclose()
        set_default_application(previous_application)
        set_default_application_factory(previous_factory)


async def test_render_html_returns_typed_artifact(
    default_executor: _FakeExecutor,
) -> None:
    artifact = await api.render_html(
        "<p>hello</p>",
        width=640,
        height=480,
        image_format="jpeg",
        quality=80,
        resource_policy=ResourcePolicy.STRICT,
        timeout_seconds=3.0,
    )

    assert artifact is default_executor.results[0]
    assert artifact.format == "jpeg"
    assert artifact.width == 1280
    assert artifact.height == 960
    call = default_executor.calls[0]
    assert "<p>hello</p>" in call.prepared.html
    assert call.options.quality == 80
    assert call.resource_policy is ResourcePolicy.STRICT
    assert call.timeout_seconds == 3.0


async def test_render_html_rejects_invalid_raster_options(
    default_executor: _FakeExecutor,
) -> None:
    with pytest.raises(InvalidRenderRequest, match="dimensions"):
        await api.render_html("<p>hello</p>", width=0)
    with pytest.raises(InvalidRenderRequest, match="format"):
        await api.render_html(
            "<p>hello</p>",
            image_format=cast("Literal['png', 'jpeg']", "gif"),
        )
    with pytest.raises(InvalidRenderRequest, match="only supported for JPEG"):
        await api.render_html("<p>hello</p>", quality=80)

    assert default_executor.calls == []


async def test_render_text_uses_text_defaults(
    default_executor: _FakeExecutor,
) -> None:
    artifact = await api.render_text(
        "hello world",
        resource_policy=ResourcePolicy.OFF,
    )

    assert artifact.width == 1000
    assert artifact.height == 713
    assert artifact.media_type == "image/png"
    call = default_executor.calls[0]
    assert call.options.width == 500
    assert call.options.device_pixel_ratio == 2.0
    assert call.resource_policy is ResourcePolicy.OFF
    assert "hello world" in call.prepared.html


async def test_render_markdown_flows_policy(
    default_executor: _FakeExecutor,
) -> None:
    artifact = await api.render_markdown(
        "# Title",
        resource_policy=ResourcePolicy.OFF,
    )

    assert artifact is default_executor.results[0]
    call = default_executor.calls[0]
    assert call.resource_policy is ResourcePolicy.OFF
    assert "Title" in call.prepared.html


async def test_prepare_markdown_uses_target_argument_names(
    default_executor: _FakeExecutor,
) -> None:
    del default_executor

    prepared = await api.prepare_markdown(
        markdown="# Prepared",
        resource_policy=ResourcePolicy.OFF,
    )

    assert "Prepared" in prepared.html
    assert "resource_strict" not in signature(api.prepare_markdown).parameters


async def test_prepare_markdown_uses_stable_validation_error(
    default_executor: _FakeExecutor,
) -> None:
    del default_executor

    with pytest.raises(InvalidRenderRequest, match="markdown"):
        await api.prepare_markdown()


def test_public_resource_helpers_do_not_expose_publisher_leases() -> None:
    assert "lease_id" not in signature(api.resolve_template_vars).parameters
    assert "lease_id" not in signature(api.to_resource_url).parameters


async def test_render_template_and_template_html(
    default_executor: _FakeExecutor,
    tmp_path: Path,
) -> None:
    (tmp_path / "page.html").write_text(
        "<html><body><h1>{{ title }}</h1></body></html>",
        encoding="utf-8",
    )

    image = await api.render_template(
        tmp_path,
        "page.html",
        {"title": "Hello"},
        width=320,
    )
    html = await api.render_template_html(tmp_path, "page.html", {"title": "Hello"})

    assert image is default_executor.results[0]
    assert default_executor.calls[0].options.width == 320
    assert "<h1>Hello</h1>" in str(html)


async def test_rasterize_html_uses_given_prepared(
    default_executor: _FakeExecutor,
) -> None:
    prepared = prepare_html("<p>direct</p>")

    artifact = await api.rasterize_html(
        prepared,
        RasterOptions(width=256, height=128),
    )

    assert artifact.width == 512
    assert artifact.height == 256
    call = default_executor.calls[0]
    assert call.prepared is prepared
    assert call.options.height == 128
