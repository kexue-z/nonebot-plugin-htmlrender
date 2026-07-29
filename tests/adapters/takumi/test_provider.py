"""Takumi provider composition and lifecycle tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import anyio
from anyio.lowlevel import checkpoint
from pydantic import ValidationError
import pytest

from nonebot_plugin_htmlrender.adapters.takumi import (
    capabilities as capabilities_module,
)
from nonebot_plugin_htmlrender.adapters.takumi import provider as provider_module
from nonebot_plugin_htmlrender.adapters.takumi import render as render_module
from nonebot_plugin_htmlrender.adapters.takumi.config import TakumiConfig
from nonebot_plugin_htmlrender.adapters.takumi.errors import (
    TakumiRuntimeError,
    TakumiUnsupportedError,
)
from nonebot_plugin_htmlrender.adapters.takumi.provider import (
    PROVIDER,
    TakumiProvider,
)
from nonebot_plugin_htmlrender.capabilities import TAKUMI
from nonebot_plugin_htmlrender.preparation import prepare_html
from nonebot_plugin_htmlrender.preparation.models import PreparedHtml, RasterOptions
from nonebot_plugin_htmlrender.providers.sdk import (
    ProviderAvailability,
    ProviderDependencies,
)
from nonebot_plugin_htmlrender.rendering import (
    ProviderExecutionError,
    ProviderLifecycleError,
    RenderedImage,
    ResourcePolicy,
    UnsupportedRequirement,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopCacheObserver
from nonebot_plugin_htmlrender.resources.config import (
    ResourceResolveMode,
    ResourceStrategy,
)
from tests.image_fixtures import encoded_image

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.resources.ports import ProviderResources
    from tests.adapters.conftest import RecordingOperationObserver

PREPARED = prepare_html("<p>prepared</p>")
OPTIONS = RasterOptions(width=320, height=240, device_pixel_ratio=2.0)


class _FakeState:
    def __init__(self) -> None:
        self.closed = False
        self.healthy = True
        self.renderer = object()

    async def aclose(self) -> None:
        self.closed = True


def _install_runtime_fakes(
    mocker: MockerFixture,
    *,
    render_result: bytes | None = None,
) -> tuple[
    list[_FakeState],
    list[tuple[_FakeState, PreparedHtml, RasterOptions, ResourceResolveMode]],
]:
    if render_result is None:
        render_result = encoded_image("png", width=640, height=480)
    created: list[_FakeState] = []
    rendered: list[
        tuple[_FakeState, PreparedHtml, RasterOptions, ResourceResolveMode]
    ] = []

    async def fake_create_runtime_state(
        config: TakumiConfig,
        *,
        resources: ProviderResources,
        cache_observer: object | None = None,
    ) -> _FakeState:
        del config, resources, cache_observer
        await anyio.sleep(0.01)
        state = _FakeState()
        created.append(state)
        return state

    def fake_require_runtime_state(handle: object) -> _FakeState:
        if not isinstance(handle, _FakeState):
            raise TakumiRuntimeError("not a runtime state")
        if handle.closed:
            raise TakumiRuntimeError("runtime is closed")
        return handle

    async def fake_rasterize(
        state: _FakeState,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resolve_mode: ResourceResolveMode = ResourceResolveMode.AUTO,
    ) -> bytes:
        rendered.append((state, prepared, options, resolve_mode))
        return render_result

    mocker.patch.object(
        render_module,
        "create_runtime_state",
        fake_create_runtime_state,
    )
    mocker.patch.object(
        render_module,
        "require_runtime_state",
        fake_require_runtime_state,
    )
    mocker.patch.object(
        provider_module,
        "require_runtime_state",
        fake_require_runtime_state,
    )
    mocker.patch.object(provider_module, "takumi_rasterize_html", fake_rasterize)
    return created, rendered


def _dependencies(
    observer: RecordingOperationObserver,
    *,
    strategy: ResourceStrategy | None = None,
) -> ProviderDependencies:
    resources = SimpleNamespace(strategy=strategy or ResourceStrategy())
    return ProviderDependencies(
        operation_observer=observer,
        cache_observer=NoopCacheObserver(),
        resources=cast("ProviderResources", resources),
        asset_publisher=None,
    )


def test_parse_settings_validates_via_pydantic() -> None:
    settings = PROVIDER.parse_settings({"max_concurrency": 2})

    assert isinstance(settings, TakumiConfig)
    assert settings.max_concurrency == 2
    with pytest.raises(ValidationError):
        PROVIDER.parse_settings({"unknown_key": True})


def test_availability_maps_backend_result(mocker: MockerFixture) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.takumi.render.takumi_availability",
        return_value=ProviderAvailability(available=False, reason="missing"),
    )

    result = PROVIDER.availability(TakumiConfig())

    assert result.available is False
    assert result.reason == "missing"


@pytest.mark.parametrize(
    ("located", "installed_version", "available", "reason"),
    [
        (False, "0.2.0", False, "not installed"),
        (True, "0.1.0", False, "Unsupported"),
        (True, "0.2.0", True, None),
    ],
)
def test_availability_checks_exact_native_version(
    mocker: MockerFixture,
    *,
    located: bool,
    installed_version: str,
    available: bool,
    reason: str | None,
) -> None:
    mocker.patch.object(
        render_module,
        "find_spec",
        return_value=object() if located else None,
    )
    mocker.patch.object(
        render_module,
        "version",
        return_value=installed_version,
    )

    status = render_module.takumi_availability()

    assert status.available is available
    if reason is not None:
        assert reason in (status.reason or "")


def test_compose_rejects_foreign_settings(
    operation_observer: RecordingOperationObserver,
) -> None:
    with pytest.raises(ProviderExecutionError, match="parse_settings"):
        PROVIDER.compose(
            cast("TakumiConfig", object()),
            _dependencies(operation_observer),
        )


def test_bootstrap_requirements_empty() -> None:
    assert PROVIDER.bootstrap_requirements(TakumiConfig()) == ()


async def test_executor_lazily_starts_and_reuses_runtime(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    created, rendered = _install_runtime_fakes(mocker)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    first = await executor.execute(PREPARED, OPTIONS)
    second = await executor.execute(PREPARED, OPTIONS)

    assert isinstance(first, RenderedImage)
    assert first == second
    assert first.format == "png"
    assert (first.width, first.height) == (640, 480)
    assert len(created) == 1
    assert len(rendered) == 2
    assert rendered[0][1] is PREPARED
    assert rendered[0][2].width == 320
    assert rendered[0][2].device_pixel_ratio == 2.0
    names = operation_observer.names()
    assert "takumi.open_runtime" in names
    assert "render.startup" in names
    assert names.count("takumi.rasterize_html") == 2


@pytest.mark.parametrize(
    ("policy", "default", "expected"),
    [
        (None, ResourceResolveMode.AUTO, ResourceResolveMode.AUTO),
        (None, ResourceResolveMode.STRICT, ResourceResolveMode.STRICT),
        (ResourcePolicy.OFF, ResourceResolveMode.STRICT, ResourceResolveMode.OFF),
        (ResourcePolicy.AUTO, ResourceResolveMode.STRICT, ResourceResolveMode.AUTO),
        (ResourcePolicy.STRICT, ResourceResolveMode.OFF, ResourceResolveMode.STRICT),
    ],
)
async def test_executor_resolves_per_call_policy_against_provider_strategy(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
    policy: ResourcePolicy | None,
    default: ResourceResolveMode,
    expected: ResourceResolveMode,
) -> None:
    _, rendered = _install_runtime_fakes(mocker)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(
            operation_observer,
            strategy=ResourceStrategy(resolve_mode=default),
        ),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    await executor.execute(PREPARED, OPTIONS, resource_policy=policy)

    assert rendered[-1][3] is expected


async def test_executor_rejects_encoded_format_mismatch(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    _install_runtime_fakes(mocker, render_result=encoded_image("jpeg"))
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    with pytest.raises(ProviderExecutionError, match="format mismatch"):
        await executor.execute(PREPARED, OPTIONS)


async def test_executor_rebuilds_after_runtime_death(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    created, _ = _install_runtime_fakes(mocker)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    await executor.execute(PREPARED, OPTIONS)
    created[0].closed = True
    await executor.execute(PREPARED, OPTIONS)

    assert len(created) == 2


async def test_executor_rebuilds_after_runtime_poisoning(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    created, rendered = _install_runtime_fakes(mocker)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    await executor.execute(PREPARED, OPTIONS)
    created[0].healthy = False
    await executor.execute(PREPARED, OPTIONS)

    assert len(created) == 2
    assert rendered[-1][0] is created[1]


async def test_concurrent_leases_build_single_runtime(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    created, rendered = _install_runtime_fakes(mocker)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    async def one_render() -> None:
        await executor.execute(PREPARED, OPTIONS)

    async with anyio.create_task_group() as task_group:
        for _ in range(3):
            task_group.start_soon(one_render)

    assert len(created) == 1
    assert len(rendered) == 3


async def test_native_errors_translate_into_stable_model(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    _install_runtime_fakes(mocker)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    async def unsupported(
        state: object,
        prepared: object,
        options: object,
        **kwargs: object,
    ) -> bytes:
        del state, prepared, options, kwargs
        raise TakumiUnsupportedError("no scripts")

    mocker.patch.object(provider_module, "takumi_rasterize_html", unsupported)
    with pytest.raises(UnsupportedRequirement, match="no scripts"):
        await executor.execute(PREPARED, OPTIONS)

    async def broken(
        state: object,
        prepared: object,
        options: object,
        **kwargs: object,
    ) -> bytes:
        del state, prepared, options, kwargs
        raise TakumiRuntimeError("native panic")

    mocker.patch.object(provider_module, "takumi_rasterize_html", broken)
    with pytest.raises(ProviderExecutionError, match="native panic"):
        await executor.execute(PREPARED, OPTIONS)


async def test_execution_timeout_maps_to_provider_error(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    _install_runtime_fakes(mocker)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    async def slow(
        state: object,
        prepared: object,
        options: object,
        **kwargs: object,
    ) -> bytes:
        del state, prepared, options, kwargs
        await anyio.sleep(5)
        return b""

    mocker.patch.object(provider_module, "takumi_rasterize_html", slow)
    with pytest.raises(ProviderExecutionError, match="timed out"):
        await executor.execute(PREPARED, OPTIONS, timeout_seconds=0.05)


async def test_startup_failure_translates_and_allows_retry(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    created, _ = _install_runtime_fakes(mocker)
    attempts: list[int] = []

    async def flaky_create(
        config: TakumiConfig,
        *,
        resources: ProviderResources,
        cache_observer: object | None = None,
    ) -> _FakeState:
        del config, resources, cache_observer
        attempts.append(1)
        if len(attempts) == 1:
            raise TakumiRuntimeError("native init failed")
        state = _FakeState()
        created.append(state)
        return state

    mocker.patch.object(render_module, "create_runtime_state", flaky_create)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )

    with pytest.raises(ProviderLifecycleError, match="native init failed"):
        await bindings.lifecycle.startup()
    await bindings.lifecycle.startup()

    assert len(attempts) == 2
    assert len(created) == 1


async def test_aclose_closes_runtime_and_is_idempotent(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    created, _ = _install_runtime_fakes(mocker)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    executor = bindings.prepared_html_executor
    assert executor is not None

    await executor.execute(PREPARED, OPTIONS)
    await bindings.lifecycle.aclose()
    await bindings.lifecycle.aclose()

    assert created[0].closed is True
    assert operation_observer.names().count("render.shutdown") == 1
    assert "takumi.close_runtime" in operation_observer.names()


async def test_typed_extension_holds_an_operation_lease_until_context_exit(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    created, _ = _install_runtime_fakes(mocker)
    mocker.patch.object(
        capabilities_module,
        "require_runtime_state",
        side_effect=lambda state: state,
    )
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    catalog = bindings.provider_capabilities
    assert catalog is not None
    capability = catalog.require(TAKUMI)

    async with (
        anyio.create_task_group() as task_group,
        capability.api() as api,
    ):
        # Observable contract: the leased runtime stays open for the whole
        # extension context, even while aclose is racing to drain it.
        del api
        assert created[0].closed is False
        task_group.start_soon(bindings.lifecycle.aclose)
        await checkpoint()
        assert created[0].closed is False

    assert created[0].closed is True


async def test_native_renderer_holds_lease_and_tracks_access(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    created, _ = _install_runtime_fakes(mocker)
    mocker.patch.object(
        capabilities_module,
        "require_runtime_state",
        side_effect=lambda state: state,
    )
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )
    catalog = bindings.provider_capabilities
    assert catalog is not None
    capability = catalog.require(TAKUMI)

    async with (
        anyio.create_task_group() as task_group,
        capability.renderer() as renderer,
    ):
        assert renderer is created[0].renderer
        task_group.start_soon(bindings.lifecycle.aclose)
        await checkpoint()
        assert created[0].closed is False

    assert created[0].closed is True
    assert (
        "takumi.native.renderer",
        {"render.backend": "takumi", "render.access": "native"},
        "success",
    ) in operation_observer.operations


async def test_probe_runs_minimal_render(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    _, rendered = _install_runtime_fakes(mocker)
    bindings = TakumiProvider().compose(
        TakumiConfig(),
        _dependencies(operation_observer),
    )

    await bindings.lifecycle.probe()

    assert len(rendered) == 1
    probe_options = rendered[0][2]
    assert probe_options.width == 8
    assert probe_options.device_pixel_ratio == 1.0
