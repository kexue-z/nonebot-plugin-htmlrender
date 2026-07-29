from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import anyio
from pydantic import ValidationError
import pytest

from nonebot_plugin_htmlrender.adapters.htmlkit import executor as executor_module
from nonebot_plugin_htmlrender.adapters.htmlkit.config import HtmlkitConfig
from nonebot_plugin_htmlrender.adapters.htmlkit.provider import (
    PROVIDER,
    HtmlkitProvider,
)
from nonebot_plugin_htmlrender.adapters.resources import (
    AnyioWorkerExecutor,
    CompositeResourceReader,
    ConfiguredLocalAccessPolicy,
    RemoteTransportExecutor,
)
from nonebot_plugin_htmlrender.bootstrap.composition import prepare_runtime
from nonebot_plugin_htmlrender.bootstrap.settings import RenderSettings
from nonebot_plugin_htmlrender.preparation import (
    PreparedStylesheet,
    RasterOptions,
    prepare_html,
)
from nonebot_plugin_htmlrender.providers.sdk import (
    ProviderAvailability,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering import (
    ProviderExecutionError,
    ProviderUnavailable,
    RenderHtmlRequest,
    ResourcePolicy,
    UnsupportedRenderOption,
    UnsupportedRequirement,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.config import (
    ResourceResolveMode,
    ResourceStrategy,
)
from nonebot_plugin_htmlrender.resources.service import ResourceService
from tests.image_fixtures import encoded_image

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.adapters.htmlkit.api import (
        ImageFetcher,
        StylesheetFetcher,
    )
    from nonebot_plugin_htmlrender.raster import RasterImageFormat
    from tests.adapters.conftest import RecordingOperationObserver


class _FakeHtmlkitAPI:
    def __init__(
        self,
        *,
        result: bytes | None = None,
        before_result: Callable[[dict[str, object]], Awaitable[None]] | None = None,
    ) -> None:
        self.result = result or encoded_image("png", width=320, height=44)
        self.before_result = before_result
        self.calls: list[dict[str, object]] = []

    async def html_to_pic(
        self,
        html: str,
        *,
        base_url: str,
        dpi: float,
        max_width: float,
        device_height: float,
        default_font_size: float,
        font_name: str,
        allow_refit: bool,
        image_format: RasterImageFormat,
        jpeg_quality: int,
        lang: str,
        culture: str,
        img_fetch_fn: ImageFetcher,
        css_fetch_fn: StylesheetFetcher,
        native_data_scheme: bool,
    ) -> bytes:
        call: dict[str, object] = {
            "html": html,
            "base_url": base_url,
            "dpi": dpi,
            "max_width": max_width,
            "device_height": device_height,
            "default_font_size": default_font_size,
            "font_name": font_name,
            "allow_refit": allow_refit,
            "image_format": image_format,
            "jpeg_quality": jpeg_quality,
            "lang": lang,
            "culture": culture,
            "img_fetch_fn": img_fetch_fn,
            "css_fetch_fn": css_fetch_fn,
            "native_data_scheme": native_data_scheme,
        }
        self.calls.append(call)
        if self.before_result is not None:
            await self.before_result(call)
        return self.result


def _dependencies(
    tmp_path: Path,
    observer: RecordingOperationObserver,
    *,
    strategy: ResourceStrategy | None = None,
) -> ProviderDependencies:
    worker = AnyioWorkerExecutor()
    reader = CompositeResourceReader(
        worker,
        remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
    )
    local_access = ConfiguredLocalAccessPolicy(
        allowed_roots=(tmp_path,),
        allow_any=False,
    )
    resources = ResourceService(
        reader=reader,
        local_access=local_access,
        strategy=strategy or ResourceStrategy(),
    )
    return ProviderDependencies(
        operation_observer=observer,
        cache_observer=NoopCacheObserver(),
        resources=resources,
        asset_publisher=None,
    )


def _install_api(mocker: MockerFixture, api: _FakeHtmlkitAPI) -> None:
    mocker.patch.object(
        executor_module,
        "load_htmlkit_api",
        return_value=api,
    )


def test_parse_settings_is_strict_and_typed() -> None:
    settings = PROVIDER.parse_settings(
        {
            "max_concurrency": 2,
            "font_name": "Noto Sans",
            "resource_resolve_mode": "strict",
        }
    )

    assert isinstance(settings, HtmlkitConfig)
    assert settings.max_concurrency == 2
    assert settings.resource_resolve_mode is ResourceResolveMode.STRICT
    with pytest.raises(ValidationError):
        PROVIDER.parse_settings({"unknown_key": True})


def test_availability_maps_installation_probe(mocker: MockerFixture) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.htmlkit.provider.htmlkit_availability",
        return_value=ProviderAvailability(available=False, reason="missing wheel"),
    )

    result = PROVIDER.availability(HtmlkitConfig())

    assert result == ProviderAvailability(available=False, reason="missing wheel")


def test_provider_declares_nonebot_bootstrap_and_resource_strategy() -> None:
    config = HtmlkitConfig(resource_resolve_mode=ResourceResolveMode.STRICT)

    requirements = PROVIDER.bootstrap_requirements(config)
    strategy = PROVIDER.resource_strategy(config)

    assert [item.plugin_name for item in requirements] == ["nonebot_plugin_htmlkit"]
    assert strategy.resolve_mode is ResourceResolveMode.STRICT


def test_compose_rejects_foreign_settings(
    tmp_path: Path,
    operation_observer: RecordingOperationObserver,
) -> None:
    with pytest.raises(ProviderExecutionError, match="parse_settings"):
        PROVIDER.compose(
            cast("HtmlkitConfig", object()),
            _dependencies(tmp_path, operation_observer),
        )


async def test_executor_maps_supported_portable_options(
    tmp_path: Path,
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    api = _FakeHtmlkitAPI(
        result=encoded_image("jpeg", width=320, height=44),
    )
    _install_api(mocker, api)
    bindings = HtmlkitProvider().compose(
        HtmlkitConfig(
            default_font_size=14,
            font_name="Noto Sans",
            language="en",
            culture="US",
            media_dpi=110,
            media_height=720,
        ),
        _dependencies(tmp_path, operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None
    prepared = prepare_html(
        "<!doctype html><html><body>hello</body></html>",
        base_url="https://example.test/root/",
        stylesheets=(
            PreparedStylesheet(
                css="body { background: url(./background.png) }",
                base_url="https://static.example.test/theme/",
            ),
        ),
    )

    result = await executor.execute(
        prepared,
        RasterOptions(
            width=320,
            device_pixel_ratio=1.0,
            format="jpeg",
            quality=72,
        ),
        resource_policy=ResourcePolicy.OFF,
    )

    assert result.format == "jpeg"
    assert (result.width, result.height) == (320, 44)
    call = api.calls[0]
    assert call["base_url"] == "https://example.test/root/"
    assert call["max_width"] == 320.0
    assert call["dpi"] == 110
    assert call["device_height"] == 720
    assert call["default_font_size"] == 14
    assert call["font_name"] == "Noto Sans"
    assert call["allow_refit"] is False
    assert call["image_format"] == "jpeg"
    assert call["jpeg_quality"] == 72
    assert call["lang"] == "en"
    assert call["culture"] == "US"
    assert call["native_data_scheme"] is True
    assert "https://static.example.test/theme/background.png" in cast(
        "str", call["html"]
    )
    assert operation_observer.names() == ["htmlkit.rasterize_html"]


async def test_executor_translates_upstream_failure_at_stable_boundary(
    tmp_path: Path,
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    async def fail(call: dict[str, object]) -> None:
        del call
        raise RuntimeError("native failure")

    api = _FakeHtmlkitAPI(before_result=fail)
    _install_api(mocker, api)
    executor = (
        HtmlkitProvider()
        .compose(
            HtmlkitConfig(),
            _dependencies(tmp_path, operation_observer),
        )
        .prepared_html_executor
    )
    assert executor is not None

    with pytest.raises(ProviderExecutionError, match="native failure"):
        await executor.execute(
            prepare_html("<p>hello</p>"),
            RasterOptions(device_pixel_ratio=1.0),
        )


async def test_executor_translates_invalid_upstream_artifact(
    tmp_path: Path,
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    api = _FakeHtmlkitAPI(result=encoded_image("jpeg"))
    _install_api(mocker, api)
    executor = (
        HtmlkitProvider()
        .compose(
            HtmlkitConfig(),
            _dependencies(tmp_path, operation_observer),
        )
        .prepared_html_executor
    )
    assert executor is not None

    with pytest.raises(ProviderExecutionError, match="format mismatch"):
        await executor.execute(
            prepare_html("<p>hello</p>"),
            RasterOptions(device_pixel_ratio=1.0, format="png"),
        )


@pytest.mark.parametrize(
    "options",
    [
        RasterOptions(device_pixel_ratio=2.0),
        RasterOptions(height=600, device_pixel_ratio=1.0),
    ],
)
async def test_executor_rejects_options_rc5_cannot_represent(
    tmp_path: Path,
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
    options: RasterOptions,
) -> None:
    api = _FakeHtmlkitAPI()
    _install_api(mocker, api)
    executor = (
        HtmlkitProvider()
        .compose(
            HtmlkitConfig(),
            _dependencies(tmp_path, operation_observer),
        )
        .prepared_html_executor
    )
    assert executor is not None

    with pytest.raises(UnsupportedRenderOption, match=r"HTMLKit 0\.1\.0rc5"):
        await executor.execute(prepare_html("<p>hello</p>"), options)

    assert api.calls == []


async def test_executor_rejects_javascript_requirement(
    tmp_path: Path,
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    api = _FakeHtmlkitAPI()
    _install_api(mocker, api)
    executor = (
        HtmlkitProvider()
        .compose(
            HtmlkitConfig(),
            _dependencies(tmp_path, operation_observer),
        )
        .prepared_html_executor
    )
    assert executor is not None

    with pytest.raises(UnsupportedRequirement, match="JavaScript"):
        await executor.execute(
            prepare_html("<script>void 0</script>"),
            RasterOptions(device_pixel_ratio=1.0),
        )

    assert api.calls == []


def test_executor_reports_trio_as_stable_provider_error(
    tmp_path: Path,
    operation_observer: RecordingOperationObserver,
) -> None:
    executor = (
        HtmlkitProvider()
        .compose(
            HtmlkitConfig(),
            _dependencies(tmp_path, operation_observer),
        )
        .prepared_html_executor
    )
    assert executor is not None

    async def run() -> None:
        with pytest.raises(ProviderUnavailable, match="asyncio-only"):
            await executor.execute(
                prepare_html("<p>hello</p>"),
                RasterOptions(device_pixel_ratio=1.0),
            )

    anyio.run(run, backend="trio")


async def test_cancellation_drains_native_work_and_holds_admission_and_limiter(
    mocker: MockerFixture,
) -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    native_cancelled = asyncio.Event()

    async def block_first(call: dict[str, object]) -> None:
        del call
        if len(api.calls) == 1:
            first_started.set()
            try:
                await release_first.wait()
            except asyncio.CancelledError:
                native_cancelled.set()
                raise

    api = _FakeHtmlkitAPI(before_result=block_first)
    _install_api(mocker, api)
    runtime = prepare_runtime(
        RenderSettings.model_validate(
            {
                "provider": "htmlkit",
                "provider_config": {"max_concurrency": 1},
            }
        )
    )
    application = runtime.build_application()
    request = RenderHtmlRequest(
        html="<p>hello</p>",
        raster=RasterOptions(device_pixel_ratio=1.0),
    )

    first = asyncio.create_task(application.renderer.render_html(request))
    await first_started.wait()
    second = asyncio.create_task(application.renderer.render_html(request))
    await anyio.sleep(0.01)

    first.cancel()
    await asyncio.sleep(0)
    first.cancel()
    await asyncio.sleep(0)
    closing = asyncio.create_task(application.aclose())
    await asyncio.sleep(0)

    assert len(api.calls) == 1
    assert not native_cancelled.is_set()
    assert not first.done()
    assert not second.done()
    assert not closing.done()

    release_first.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    second_result = await second
    await closing

    assert second_result.format == "png"
    assert len(api.calls) == 2


async def test_timeout_waits_for_native_drain_before_reporting(
    tmp_path: Path,
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def block(call: dict[str, object]) -> None:
        del call
        started.set()
        await release.wait()

    api = _FakeHtmlkitAPI(before_result=block)
    _install_api(mocker, api)
    executor = (
        HtmlkitProvider()
        .compose(
            HtmlkitConfig(),
            _dependencies(tmp_path, operation_observer),
        )
        .prepared_html_executor
    )
    assert executor is not None

    task = asyncio.create_task(
        executor.execute(
            prepare_html("<p>hello</p>"),
            RasterOptions(device_pixel_ratio=1.0),
            timeout_seconds=0.01,
        )
    )
    await started.wait()
    await anyio.sleep(0.02)

    assert not task.done()
    release.set()
    with pytest.raises(ProviderExecutionError, match="timed out"):
        await task
