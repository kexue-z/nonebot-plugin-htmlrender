from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from exceptiongroup import BaseExceptionGroup
import pytest

from nonebot_plugin_htmlrender.bootstrap.composition import _ComposedLifecycle

if TYPE_CHECKING:
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


def _lifecycle(
    engine: _Component,
    resources: _Component,
    templates: _Component,
    publisher: _Component,
) -> _ComposedLifecycle:
    return _ComposedLifecycle(
        engine=cast("ApplicationLifecycle", engine),
        resources=cast("ResourceService", resources),
        templates=cast("JinjaTemplateCompiler", templates),
        publisher=cast("AssetPublisher", publisher),
    )


async def test_startup_failure_rolls_back_composition_caches_and_can_retry() -> None:
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

    assert events == [
        "publisher.startup",
        "engine.startup",
        "templates.clear",
        "resources.clear",
        "publisher.clear",
    ]

    await lifecycle.startup()
    assert events[-2:] == ["publisher.startup", "engine.startup"]


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
