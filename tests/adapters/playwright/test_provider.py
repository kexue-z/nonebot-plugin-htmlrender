"""Playwright provider composition and stable-boundary tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from playwright.async_api import Error as PlaywrightError
from pydantic import ValidationError
import pytest

from nonebot_plugin_htmlrender.adapters.playwright import provider as provider_module
from nonebot_plugin_htmlrender.adapters.playwright.config import PlaywrightConfig
from nonebot_plugin_htmlrender.adapters.playwright.provider import (
    PROVIDER,
    PlaywrightProvider,
)
from nonebot_plugin_htmlrender.preparation import prepare_html
from nonebot_plugin_htmlrender.preparation.materialize import (
    AssetMaterializationError,
)
from nonebot_plugin_htmlrender.preparation.models import PreparedHtml, RasterOptions
from nonebot_plugin_htmlrender.providers.sdk import (
    ProviderAvailability,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering import (
    ProviderExecutionError,
    RenderedImage,
    ResourcePolicy,
    ResourceResolutionError,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.config import (
    ResourceResolveMode,
    ResourceStrategy,
)
from tests.image_fixtures import encoded_image, rendered_image

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.adapters.playwright.render import PlaywrightLease
    from nonebot_plugin_htmlrender.resources.ports import ProviderResources
    from tests.adapters.conftest import RecordingOperationObserver

PREPARED = prepare_html("<p>prepared</p>")


def _dependencies(observer: RecordingOperationObserver) -> ProviderDependencies:
    resources = SimpleNamespace(strategy=ResourceStrategy())
    return ProviderDependencies(
        operation_observer=observer,
        cache_observer=NoopCacheObserver(),
        resources=cast("ProviderResources", resources),
        asset_publisher=None,
    )


def test_parse_settings_validates_via_pydantic() -> None:
    settings = PROVIDER.parse_settings({"skip_browser_install": True})

    assert isinstance(settings, PlaywrightConfig)
    assert settings.skip_browser_install is True
    with pytest.raises(ValidationError):
        PROVIDER.parse_settings({"engine": "definitely-not-a-browser"})


def test_availability_uses_parsed_settings(mocker: MockerFixture) -> None:
    seen: list[PlaywrightConfig] = []

    def fake_available(cfg: PlaywrightConfig) -> ProviderAvailability:
        seen.append(cfg)
        return ProviderAvailability(available=False, reason="nope")

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.availability.playwright_availability",
        fake_available,
    )
    config = PlaywrightConfig()

    result = PROVIDER.availability(config)

    assert result.available is False
    assert result.reason == "nope"
    assert seen == [config]


def test_availability_reports_missing_playwright_extra(
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.availability._playwright_is_installed",
        return_value=False,
    )

    result = PROVIDER.availability(PlaywrightConfig())

    assert result.available is False
    assert "[playwright]" in (result.reason or "")


def test_bootstrap_requirements_declare_no_external_plugins() -> None:
    plain = PlaywrightConfig()
    assert PROVIDER.bootstrap_requirements(plain) == ()

    # The filehost transport is served by the htmlrender-owned hosted asset
    # store, so even a filehost policy needs no external NoneBot plugin.
    filehost = PlaywrightConfig.model_validate(
        {"local_local_resource_policy": "filehost"}
    )
    assert PROVIDER.bootstrap_requirements(filehost) == ()


def test_compose_uses_constructor_injected_settings(
    operation_observer: RecordingOperationObserver,
) -> None:
    config = PlaywrightConfig.model_validate({"skip_browser_install": True})

    bindings = PlaywrightProvider().compose(config, _dependencies(operation_observer))

    assert bindings.prepared_html_executor is not None
    assert bindings.lifecycle is not None
    assert bindings.provider_capabilities is not None


async def test_standard_raster_uses_injected_operation_observer(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    lease = object()
    expected = rendered_image("png", width=1600, height=719)

    class FakeEngine:
        def __init__(
            self,
            config: PlaywrightConfig,
            *,
            operation_observer: object,
        ) -> None:
            del config
            assert operation_observer is not None

        async def create_lease(self) -> object:
            return lease

        @staticmethod
        def is_alive(value: object) -> bool:
            return value is lease

        @staticmethod
        async def close_lease(value: object) -> None:
            assert value is lease

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.render.PlaywrightEngine",
        FakeEngine,
    )
    rasterize = mocker.patch.object(
        provider_module,
        "_rasterize",
        new=mocker.AsyncMock(return_value=expected),
    )
    bindings = PlaywrightProvider().compose(
        PlaywrightConfig(),
        _dependencies(operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    result = await executor.execute(PREPARED, RasterOptions())

    assert result is expected
    rasterize.assert_awaited_once()
    assert "playwright.html_render.rasterize_html" in operation_observer.names()


def test_compose_rejects_foreign_settings(
    operation_observer: RecordingOperationObserver,
) -> None:
    with pytest.raises(ProviderExecutionError, match="parse_settings"):
        PROVIDER.compose(
            cast("PlaywrightConfig", object()),
            _dependencies(operation_observer),
        )


async def test_rasterize_maps_raster_options(mocker: MockerFixture) -> None:
    captured: dict[str, object] = {}
    encoded = encoded_image("jpeg", width=1280, height=1337)

    async def fake_render_prepared_html(
        prepared: PreparedHtml,
        **kwargs: object,
    ) -> bytes:
        captured["prepared"] = prepared
        captured.update(kwargs)
        return encoded

    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations.render_prepared_html",
        fake_render_prepared_html,
    )

    lease = cast("PlaywrightLease", object())
    resources = cast(
        "ProviderResources",
        SimpleNamespace(
            strategy=ResourceStrategy(resolve_mode=ResourceResolveMode.STRICT)
        ),
    )

    result = await provider_module._rasterize(
        lease,
        PREPARED,
        RasterOptions(width=640, height=None, format="jpeg", quality=70),
        ResourcePolicy.AUTO,
        resources=resources,
        asset_publisher=None,
    )

    assert isinstance(result, RenderedImage)
    assert bytes(result) == encoded
    assert result.format == "jpeg"
    assert (result.width, result.height) == (1280, 1337)
    assert captured["prepared"] is PREPARED
    assert captured["lease"] is lease
    assert captured["resources"] is resources
    assert captured["asset_publisher"] is None
    assert captured["resolve_mode"] is ResourceResolveMode.AUTO
    assert captured["telemetry_op"] == "playwright.html_render.rasterize_html"
    render_config = captured["render"]
    page = getattr(render_config, "page", None)
    screenshot = getattr(render_config, "screenshot", None)
    assert page is not None
    assert screenshot is not None
    assert page.viewport.width == 640
    assert page.viewport.height == 10
    assert screenshot.full_page is True
    assert screenshot.format == "jpeg"
    assert screenshot.quality == 70
    assert screenshot.device_scale_factor == 2.0


async def test_rasterize_rejects_encoded_format_mismatch(
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.playwright.operations.render_prepared_html",
        new=mocker.AsyncMock(return_value=encoded_image("png")),
    )
    lease = cast("PlaywrightLease", object())
    resources = cast(
        "ProviderResources",
        SimpleNamespace(strategy=ResourceStrategy()),
    )

    with pytest.raises(ValueError, match="format mismatch"):
        await provider_module._rasterize(
            lease,
            PREPARED,
            RasterOptions(format="jpeg", quality=70),
            None,
            resources=resources,
            asset_publisher=None,
        )


def test_translate_maps_native_errors() -> None:
    with (
        pytest.raises(ProviderExecutionError, match="render failed"),
        provider_module._translate("render", ProviderExecutionError),
    ):
        raise PlaywrightError("render failed")

    with (
        pytest.raises(ResourceResolutionError, match="missing asset"),
        provider_module._translate("render", ProviderExecutionError),
    ):
        raise AssetMaterializationError("missing asset")
