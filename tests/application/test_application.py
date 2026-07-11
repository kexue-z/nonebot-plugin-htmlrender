from __future__ import annotations

from dataclasses import dataclass, field

import anyio
import anyio.lowlevel
import pytest

from nonebot_plugin_htmlrender.application import (
    Application,
    Renderer,
    RendererBindings,
)
from nonebot_plugin_htmlrender.rendering import (
    CapabilityCatalog,
    CapabilityKey,
    ProviderLifecycleError,
)


@dataclass
class _FakeLifecycle:
    startup_calls: int = 0
    probe_calls: int = 0
    aclose_calls: int = 0
    startup_failures: list[Exception] = field(default_factory=list)

    async def startup(self) -> None:
        self.startup_calls += 1
        await anyio.lowlevel.checkpoint()
        if self.startup_failures:
            raise self.startup_failures.pop(0)

    async def probe(self) -> None:
        self.probe_calls += 1

    async def aclose(self) -> None:
        self.aclose_calls += 1


def _application(lifecycle: _FakeLifecycle) -> Application:
    return Application(
        renderer=Renderer(RendererBindings()),
        lifecycle=lifecycle,
    )


async def test_startup_is_idempotent() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    await app.startup()
    await app.startup()

    assert lifecycle.startup_calls == 1


async def test_concurrent_startup_invokes_lifecycle_once() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(app.startup)
        task_group.start_soon(app.startup)
        task_group.start_soon(app.startup)

    assert lifecycle.startup_calls == 1


async def test_startup_failure_allows_retry() -> None:
    lifecycle = _FakeLifecycle(startup_failures=[RuntimeError("boom")])
    app = _application(lifecycle)

    with pytest.raises(RuntimeError, match="boom"):
        await app.startup()
    await app.startup()

    assert lifecycle.startup_calls == 2


async def test_aclose_is_idempotent_and_blocks_restart() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    await app.startup()
    await app.aclose()
    await app.aclose()

    assert lifecycle.aclose_calls == 1
    with pytest.raises(ProviderLifecycleError, match="closed"):
        await app.startup()


async def test_aclose_without_startup_still_closes_lifecycle() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    await app.aclose()

    assert lifecycle.aclose_calls == 1


async def test_probe_delegates_to_lifecycle() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    await app.probe()

    assert lifecycle.probe_calls == 1


def test_capability_catalog_defaults_to_empty() -> None:
    app = _application(_FakeLifecycle())

    class _Marker:
        pass

    assert app.capabilities.names() == frozenset()
    assert app.capabilities.get(CapabilityKey("test.marker", _Marker)) is None


def test_capability_catalog_passthrough() -> None:
    class _Marker:
        pass

    marker = _Marker()
    key = CapabilityKey("test.marker", _Marker)
    catalog = CapabilityCatalog().with_capability(key, marker)
    app = Application(
        renderer=Renderer(RendererBindings()),
        lifecycle=_FakeLifecycle(),
        capabilities=catalog,
    )

    assert app.capabilities.require(key) is marker
