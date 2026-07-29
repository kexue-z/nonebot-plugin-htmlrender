from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from exceptiongroup import BaseExceptionGroup
import pytest

from nonebot_plugin_htmlrender.bootstrap.composition import _ComposedLifecycle

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.adapters.resources import RemoteTransportExecutor
    from nonebot_plugin_htmlrender.adapters.templates import JinjaTemplateCompiler
    from nonebot_plugin_htmlrender.rendering.ports import ApplicationLifecycle
    from nonebot_plugin_htmlrender.resources.ports import AssetPublisher
    from nonebot_plugin_htmlrender.resources.service import ResourceService


@dataclass
class _Component:
    name: str
    events: list[str]
    startup_errors: list[BaseException] = field(default_factory=list)
    clear_errors: list[BaseException] = field(default_factory=list)
    close_errors: list[BaseException] = field(default_factory=list)

    async def startup(self) -> None:
        self.events.append(f"{self.name}.startup")
        if self.startup_errors:
            raise self.startup_errors.pop(0)

    async def probe(self) -> None:
        self.events.append(f"{self.name}.probe")

    async def clear(self) -> None:
        self.events.append(f"{self.name}.clear")
        if self.clear_errors:
            raise self.clear_errors.pop(0)

    async def aclose(self) -> None:
        self.events.append(f"{self.name}.aclose")
        if self.close_errors:
            raise self.close_errors.pop(0)


class _Transport:
    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


def _lifecycle(
    engine: _Component,
    resources: _Component,
    templates: _Component,
    publisher: _Component,
    transport: _Transport | None = None,
) -> _ComposedLifecycle:
    return _ComposedLifecycle(
        engine=cast("ApplicationLifecycle", engine),
        resources=cast("ResourceService", resources),
        templates=cast("JinjaTemplateCompiler", templates),
        publisher=cast("AssetPublisher", publisher),
        remote_transport=cast("RemoteTransportExecutor", transport or _Transport()),
    )


async def test_startup_failure_rolls_back_completed_steps_in_reverse_and_retries() -> (
    None
):
    events: list[str] = []
    engine = _Component(
        "engine",
        events,
        startup_errors=[RuntimeError("engine unavailable")],
    )
    resources = _Component("resources", events)
    templates = _Component("templates", events)
    publisher = _Component("publisher", events)
    lifecycle = _lifecycle(engine, resources, templates, publisher)

    with pytest.raises(RuntimeError, match="engine unavailable"):
        await lifecycle.startup()

    # The one completed step (publisher.startup) is rolled back first, then the
    # stateless caches are cleared.
    assert events == [
        "publisher.startup",
        "engine.startup",
        "publisher.clear",
        "templates.clear",
        "resources.clear",
    ]

    await lifecycle.startup()
    assert events[-2:] == ["publisher.startup", "engine.startup"]


async def test_startup_does_not_roll_back_a_step_that_never_started() -> None:
    events: list[str] = []
    engine = _Component("engine", events)
    resources = _Component("resources", events)
    templates = _Component("templates", events)
    publisher = _Component(
        "publisher",
        events,
        startup_errors=[RuntimeError("publisher unavailable")],
    )
    lifecycle = _lifecycle(engine, resources, templates, publisher)

    with pytest.raises(RuntimeError, match="publisher unavailable"):
        await lifecycle.startup()

    # Publisher startup failed, so its undo never runs and the engine never
    # started; only the stateless caches are cleared.
    assert events == [
        "publisher.startup",
        "templates.clear",
        "resources.clear",
    ]


async def test_rollback_failure_poisons_composition_and_blocks_retry() -> None:
    events: list[str] = []
    engine = _Component(
        "engine",
        events,
        startup_errors=[RuntimeError("engine unavailable")],
    )
    resources = _Component("resources", events)
    templates = _Component("templates", events)
    publisher = _Component(
        "publisher",
        events,
        clear_errors=[RuntimeError("publisher rollback failed")],
    )
    lifecycle = _lifecycle(engine, resources, templates, publisher)

    with pytest.raises(BaseExceptionGroup) as captured:
        await lifecycle.startup()
    assert "poisoned" in str(captured.value)
    assert {str(error) for error in captured.value.exceptions} == {
        "engine unavailable",
        "publisher rollback failed",
    }

    from nonebot_plugin_htmlrender.rendering.errors import (  # noqa: PLC0415
        ProviderLifecycleError,
    )

    with pytest.raises(ProviderLifecycleError, match="poisoned"):
        await lifecycle.startup()


async def test_shutdown_attempts_every_component_and_is_retryable() -> None:
    events: list[str] = []
    engine = _Component(
        "engine",
        events,
        close_errors=[RuntimeError("engine close failed")],
    )
    resources = _Component("resources", events)
    templates = _Component(
        "templates",
        events,
        clear_errors=[RuntimeError("template clear failed")],
    )
    publisher = _Component(
        "publisher",
        events,
        clear_errors=[RuntimeError("publisher clear failed")],
    )
    lifecycle = _lifecycle(engine, resources, templates, publisher)

    with pytest.raises(BaseExceptionGroup) as captured:
        await lifecycle.aclose()

    assert [str(error) for error in captured.value.exceptions] == [
        "engine close failed",
        "template clear failed",
        "publisher clear failed",
    ]
    assert events == [
        "engine.aclose",
        "templates.clear",
        "resources.clear",
        "publisher.clear",
        "publisher.aclose",
    ]

    await lifecycle.aclose()
    assert events[-5:] == [
        "engine.aclose",
        "templates.clear",
        "resources.clear",
        "publisher.clear",
        "publisher.aclose",
    ]
