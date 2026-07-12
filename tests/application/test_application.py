from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import anyio
import anyio.lowlevel
from exceptiongroup import ExceptionGroup
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

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.preparation.service import HtmlPreparer
    from nonebot_plugin_htmlrender.resources.service import ResourceService


_PREPARATION = cast("HtmlPreparer", object())
_RESOURCES = cast("ResourceService", object())


@dataclass
class _FakeLifecycle:
    startup_calls: int = 0
    probe_calls: int = 0
    aclose_calls: int = 0
    startup_failures: list[Exception] = field(default_factory=list)
    aclose_failures: list[Exception] = field(default_factory=list)

    async def startup(self) -> None:
        self.startup_calls += 1
        await anyio.lowlevel.checkpoint()
        if self.startup_failures:
            raise self.startup_failures.pop(0)

    async def probe(self) -> None:
        self.probe_calls += 1

    async def aclose(self) -> None:
        self.aclose_calls += 1
        if self.aclose_failures:
            raise self.aclose_failures.pop(0)


def _application(lifecycle: _FakeLifecycle) -> Application:
    return Application(
        renderer=Renderer(RendererBindings()),
        preparation=_PREPARATION,
        resources=_RESOURCES,
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

    with pytest.raises(ProviderLifecycleError, match="boom") as captured:
        await app.startup()
    assert isinstance(captured.value.__cause__, RuntimeError)
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


async def test_failed_close_can_be_retried_but_cannot_restart() -> None:
    lifecycle = _FakeLifecycle(aclose_failures=[RuntimeError("cache busy")])
    app = _application(lifecycle)
    await app.startup()

    with pytest.raises(ProviderLifecycleError, match="cache busy") as captured:
        await app.aclose()
    assert isinstance(captured.value.__cause__, RuntimeError)
    with pytest.raises(ProviderLifecycleError, match="closing"):
        await app.startup()

    await app.aclose()
    await app.aclose()

    assert lifecycle.aclose_calls == 2


async def test_lifecycle_exception_group_is_exposed_as_stable_error() -> None:
    failure = ExceptionGroup(
        "cleanup failed",
        [RuntimeError("engine close failed"), RuntimeError("cache clear failed")],
    )
    app = _application(_FakeLifecycle(aclose_failures=[failure]))

    with pytest.raises(ProviderLifecycleError, match="cleanup failed") as captured:
        await app.aclose()

    assert captured.value.__cause__ is failure


async def test_probe_delegates_to_lifecycle() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    await app.probe()

    assert lifecycle.startup_calls == 1
    assert lifecycle.probe_calls == 1

    await app.aclose()
    with pytest.raises(ProviderLifecycleError, match="closed"):
        await app.probe()


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
        preparation=_PREPARATION,
        resources=_RESOURCES,
        lifecycle=_FakeLifecycle(),
        capabilities=catalog,
    )

    assert app.capabilities.require(key) is marker


def test_application_exposes_composition_owned_services() -> None:
    app = _application(_FakeLifecycle())

    assert app.preparation is _PREPARATION
    assert app.resources is _RESOURCES
