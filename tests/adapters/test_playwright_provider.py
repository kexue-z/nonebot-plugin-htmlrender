from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError
from pydantic import ValidationError
import pytest

from nonebot_plugin_htmlrender.adapters.playwright import provider as provider_module
from nonebot_plugin_htmlrender.adapters.playwright.provider import (
    PROVIDER,
    PlaywrightProvider,
)
from nonebot_plugin_htmlrender.backend.base import RenderRuntime, RenderSession
from nonebot_plugin_htmlrender.backend.factory import BackendAvailability
from nonebot_plugin_htmlrender.backend.playwright.config import (
    PlaywrightConfig,
    get_playwright_config,
    register_playwright_config_provider,
)
from nonebot_plugin_htmlrender.consts import RenderBackend
from nonebot_plugin_htmlrender.preparation.materialize import (
    AssetMaterializationError,
)
from nonebot_plugin_htmlrender.preparation.models import PreparedHtml, RasterOptions
from nonebot_plugin_htmlrender.providers.sdk import ProviderDependencies
from nonebot_plugin_htmlrender.rendering import (
    ProviderExecutionError,
    ResourcePolicy,
    ResourceResolutionError,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopCacheObserver

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_mock import MockerFixture

    from tests.adapters.conftest import RecordingOperationObserver

PREPARED = PreparedHtml(html="<p>prepared</p>")


@pytest.fixture(autouse=True)
def _reset_config_provider() -> Iterator[None]:
    previous = register_playwright_config_provider(None)
    yield
    register_playwright_config_provider(previous)


def _dependencies(observer: RecordingOperationObserver) -> ProviderDependencies:
    return ProviderDependencies(
        operation_observer=observer,
        cache_observer=NoopCacheObserver(),
    )


def test_parse_settings_validates_via_pydantic() -> None:
    settings = PROVIDER.parse_settings({"skip_browser_install": True})

    assert isinstance(settings, PlaywrightConfig)
    assert settings.skip_browser_install is True
    with pytest.raises(ValidationError):
        PROVIDER.parse_settings({"engine": "definitely-not-a-browser"})


def test_availability_uses_parsed_settings(mocker: MockerFixture) -> None:
    seen: list[PlaywrightConfig] = []

    def fake_available(cfg: PlaywrightConfig | None = None) -> BackendAvailability:
        assert cfg is not None
        seen.append(cfg)
        return BackendAvailability(available=False, reason="nope")

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.playwright.render."
        "is_playwright_backend_available",
        fake_available,
    )
    config = PlaywrightConfig()

    result = PROVIDER.availability(config)

    assert result.available is False
    assert result.reason == "nope"
    assert seen == [config]


def test_bootstrap_requirements_reflect_filehost_policy() -> None:
    plain = PlaywrightConfig()
    assert PROVIDER.bootstrap_requirements(plain) == ()

    filehost = PlaywrightConfig.model_validate(
        {"local_local_resource_policy": "filehost"}
    )
    requirements = PROVIDER.bootstrap_requirements(filehost)
    assert [item.plugin_name for item in requirements] == ["nonebot_plugin_filehost"]

    disabled = PlaywrightConfig.model_validate(
        {
            "local_local_resource_policy": "filehost",
            "resource_resolve_mode": "off",
        }
    )
    assert PROVIDER.bootstrap_requirements(disabled) == ()


def test_compose_routes_config_reads_to_settings(
    operation_observer: RecordingOperationObserver,
) -> None:
    config = PlaywrightConfig.model_validate({"skip_browser_install": True})

    bindings = PlaywrightProvider().compose(config, _dependencies(operation_observer))

    assert bindings.prepared_html_executor is not None
    assert bindings.lifecycle is not None
    assert get_playwright_config() is config


def test_compose_rejects_foreign_settings(
    operation_observer: RecordingOperationObserver,
) -> None:
    with pytest.raises(ProviderExecutionError, match="parse_settings"):
        PROVIDER.compose(object(), _dependencies(operation_observer))


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (None, True),
        (ResourcePolicy.STRICT, True),
        (ResourcePolicy.AUTO, False),
        (ResourcePolicy.OFF, None),
    ],
)
def test_strict_assets_mapping(
    policy: ResourcePolicy | None,
    expected: bool | None,  # noqa: FBT001 -- pytest passes params by name
) -> None:
    assert provider_module._strict_assets(policy) == expected


async def test_rasterize_maps_raster_options(mocker: MockerFixture) -> None:
    captured: dict[str, object] = {}

    async def fake_render_prepared_html(
        prepared: PreparedHtml,
        **kwargs: object,
    ) -> bytes:
        captured["prepared"] = prepared
        captured.update(kwargs)
        return b"img"

    mocker.patch.object(
        provider_module,
        "render_prepared_html",
        fake_render_prepared_html,
    )

    async def _noop() -> None:
        return None

    runtime = RenderRuntime(
        backend=RenderBackend.PLAYWRIGHT,
        handle=object(),
        _aclose=_noop,
    )
    session = RenderSession(runtime=runtime, handle=object(), _aclose=_noop)

    result = await provider_module._rasterize(
        session,
        PREPARED,
        RasterOptions(width=640, height=None, format="jpeg", quality=70),
        ResourcePolicy.AUTO,
    )

    assert result == b"img"
    assert captured["prepared"] is PREPARED
    assert captured["session"] is session
    assert captured["strict_assets"] is False
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
