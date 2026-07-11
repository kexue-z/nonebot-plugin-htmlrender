from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.api._default import set_default_application
from nonebot_plugin_htmlrender.bootstrap.composition import ComposedRuntime
from nonebot_plugin_htmlrender.bootstrap.plugin import run_shutdown, run_startup
from nonebot_plugin_htmlrender.bootstrap.settings import RenderSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass
class _FakeApplication:
    startup_calls: int = 0
    probe_calls: int = 0
    aclose_calls: int = 0

    async def startup(self) -> None:
        self.startup_calls += 1

    async def probe(self) -> None:
        self.probe_calls += 1

    async def aclose(self) -> None:
        self.aclose_calls += 1


@pytest.fixture
def fake_default_application() -> Iterator[_FakeApplication]:
    application = _FakeApplication()
    previous = set_default_application(application)  # type: ignore[arg-type]
    yield application
    set_default_application(previous)


def _runtime(settings: RenderSettings) -> ComposedRuntime:
    return ComposedRuntime(
        settings=settings,
        provider=None,
        provider_settings=None,
        plugin_requirements=(),
    )


async def test_run_startup_skips_without_provider(
    fake_default_application: _FakeApplication,
) -> None:
    await run_startup(_runtime(RenderSettings()))

    assert fake_default_application.startup_calls == 0


async def test_run_startup_skips_in_off_mode(
    fake_default_application: _FakeApplication,
) -> None:
    settings = RenderSettings.model_validate({"provider": "fake", "startup": "off"})

    await run_startup(_runtime(settings))

    assert fake_default_application.startup_calls == 0


async def test_run_startup_warmup_starts_without_probe(
    fake_default_application: _FakeApplication,
) -> None:
    settings = RenderSettings.model_validate({"provider": "fake", "startup": "warmup"})

    await run_startup(_runtime(settings))

    assert fake_default_application.startup_calls == 1
    assert fake_default_application.probe_calls == 0


async def test_run_startup_probe_starts_and_probes(
    fake_default_application: _FakeApplication,
) -> None:
    settings = RenderSettings.model_validate({"provider": "fake", "startup": "probe"})

    await run_startup(_runtime(settings))

    assert fake_default_application.startup_calls == 1
    assert fake_default_application.probe_calls == 1


async def test_run_startup_wraps_failures(
    fake_default_application: _FakeApplication,
) -> None:
    async def broken_startup() -> None:
        raise ValueError("engine exploded")

    fake_default_application.startup = broken_startup  # type: ignore[method-assign]
    settings = RenderSettings.model_validate({"provider": "fake", "startup": "warmup"})

    with pytest.raises(RuntimeError, match="startup failed"):
        await run_startup(_runtime(settings))


async def test_run_shutdown_closes_only_built_application(
    fake_default_application: _FakeApplication,
) -> None:
    await run_shutdown()
    assert fake_default_application.aclose_calls == 1

    set_default_application(None)
    await run_shutdown()
    assert fake_default_application.aclose_calls == 1
