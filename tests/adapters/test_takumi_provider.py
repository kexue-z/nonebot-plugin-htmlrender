from __future__ import annotations

from typing import TYPE_CHECKING

import anyio
from pydantic import ValidationError
import pytest

from nonebot_plugin_htmlrender.adapters.takumi import provider as provider_module
from nonebot_plugin_htmlrender.adapters.takumi.provider import (
    PROVIDER,
    TakumiProvider,
)
from nonebot_plugin_htmlrender.backend.factory import BackendAvailability
from nonebot_plugin_htmlrender.backend.takumi.config import TakumiConfig
from nonebot_plugin_htmlrender.backend.takumi.errors import (
    TakumiRuntimeError,
    TakumiUnsupportedError,
)
from nonebot_plugin_htmlrender.preparation.models import PreparedHtml, RasterOptions
from nonebot_plugin_htmlrender.providers.sdk import ProviderDependencies
from nonebot_plugin_htmlrender.rendering import (
    ProviderExecutionError,
    ProviderLifecycleError,
    UnsupportedRequirement,
)
from nonebot_plugin_htmlrender.rendering.observers import NoopCacheObserver

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from tests.adapters.conftest import RecordingOperationObserver

PREPARED = PreparedHtml(html="<p>prepared</p>")
OPTIONS = RasterOptions(width=320, height=240, device_pixel_ratio=1.0)


class _FakeState:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _install_runtime_fakes(
    mocker: MockerFixture,
    *,
    render_result: bytes = b"png-bytes",
) -> tuple[list[_FakeState], list[tuple[_FakeState, PreparedHtml, RasterOptions]]]:
    created: list[_FakeState] = []
    rendered: list[tuple[_FakeState, PreparedHtml, RasterOptions]] = []

    async def fake_create_runtime_state(
        config: TakumiConfig,
        *,
        cache_observer: object | None = None,
    ) -> _FakeState:
        del config, cache_observer
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
    ) -> bytes:
        rendered.append((state, prepared, options))
        return render_result

    mocker.patch.object(
        provider_module,
        "create_runtime_state",
        fake_create_runtime_state,
    )
    mocker.patch.object(
        provider_module,
        "require_runtime_state",
        fake_require_runtime_state,
    )
    mocker.patch.object(provider_module, "takumi_rasterize_html", fake_rasterize)
    return created, rendered


def _dependencies(observer: RecordingOperationObserver) -> ProviderDependencies:
    return ProviderDependencies(
        operation_observer=observer,
        cache_observer=NoopCacheObserver(),
    )


def test_parse_settings_validates_via_pydantic() -> None:
    settings = PROVIDER.parse_settings({"max_concurrency": 2})

    assert isinstance(settings, TakumiConfig)
    assert settings.max_concurrency == 2
    with pytest.raises(ValidationError):
        PROVIDER.parse_settings({"unknown_key": True})


def test_availability_maps_backend_result(mocker: MockerFixture) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.render.is_takumi_backend_available",
        return_value=BackendAvailability(available=False, reason="missing"),
    )

    result = PROVIDER.availability(TakumiConfig())

    assert result.available is False
    assert result.reason == "missing"


def test_compose_rejects_foreign_settings(
    operation_observer: RecordingOperationObserver,
) -> None:
    with pytest.raises(ProviderExecutionError, match="parse_settings"):
        PROVIDER.compose(object(), _dependencies(operation_observer))


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

    assert first == second == b"png-bytes"
    assert len(created) == 1
    assert len(rendered) == 2
    assert rendered[0][1] is PREPARED
    names = operation_observer.names()
    assert "takumi.open_runtime" in names
    assert "render.startup" in names
    assert names.count("takumi.rasterize_html") == 2


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
    ) -> bytes:
        del state, prepared, options
        raise TakumiUnsupportedError("no scripts")

    mocker.patch.object(provider_module, "takumi_rasterize_html", unsupported)
    with pytest.raises(UnsupportedRequirement, match="no scripts"):
        await executor.execute(PREPARED, OPTIONS)

    async def broken(state: object, prepared: object, options: object) -> bytes:
        del state, prepared, options
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

    async def slow(state: object, prepared: object, options: object) -> bytes:
        del state, prepared, options
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
        cache_observer: object | None = None,
    ) -> _FakeState:
        del config, cache_observer
        attempts.append(1)
        if len(attempts) == 1:
            raise TakumiRuntimeError("native init failed")
        state = _FakeState()
        created.append(state)
        return state

    mocker.patch.object(provider_module, "create_runtime_state", flaky_create)
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
