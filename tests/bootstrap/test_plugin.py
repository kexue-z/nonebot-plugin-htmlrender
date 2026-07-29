from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender.api._default import set_default_application
from nonebot_plugin_htmlrender.bootstrap import plugin as plugin_module
from nonebot_plugin_htmlrender.bootstrap.composition import ComposedRuntime
from nonebot_plugin_htmlrender.bootstrap.plugin import run_shutdown, run_startup
from nonebot_plugin_htmlrender.bootstrap.settings import RenderSettings
from nonebot_plugin_htmlrender.rendering.errors import ProviderUnavailable
from nonebot_plugin_htmlrender.resources.config import ResourceStrategy

if TYPE_CHECKING:
    from collections.abc import Iterator

    from nonebot_plugin_htmlrender.application import Application


@dataclass
class _FakeApplication:
    startup_calls: int = 0
    probe_calls: int = 0
    aclose_calls: int = 0
    startup_error: Exception | None = None
    probe_error: Exception | None = None

    async def startup(self) -> None:
        self.startup_calls += 1
        if self.startup_error is not None:
            raise self.startup_error

    async def probe(self) -> None:
        self.probe_calls += 1
        if self.probe_error is not None:
            raise self.probe_error

    async def aclose(self) -> None:
        self.aclose_calls += 1


@pytest.fixture
def fake_default_application() -> Iterator[_FakeApplication]:
    application = _FakeApplication()
    previous = set_default_application(cast("Application", application))
    yield application
    set_default_application(previous)


def _runtime(settings: RenderSettings) -> ComposedRuntime:
    return ComposedRuntime(
        settings=settings,
        provider=None,
        provider_settings=None,
        plugin_requirements=(),
        resource_strategy=ResourceStrategy(),
    )


def test_required_nonebot_plugin_fails_before_runtime_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plugin_module, "find_spec", lambda _name: None)

    with pytest.raises(ProviderUnavailable, match="required_plugin"):
        plugin_module._require_optional_plugin(
            plugin_name="required_plugin",
            enabled=True,
            required=True,
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
    fake_default_application.startup_error = ValueError("engine exploded")
    settings = RenderSettings.model_validate({"provider": "fake", "startup": "warmup"})

    with pytest.raises(RuntimeError, match="startup failed"):
        await run_startup(_runtime(settings))

    assert fake_default_application.aclose_calls == 0


async def test_run_startup_closes_runtime_when_probe_fails(
    fake_default_application: _FakeApplication,
) -> None:
    fake_default_application.probe_error = ValueError("probe exploded")
    settings = RenderSettings.model_validate({"provider": "fake", "startup": "probe"})

    with pytest.raises(RuntimeError, match="startup failed"):
        await run_startup(_runtime(settings))

    assert fake_default_application.startup_calls == 1
    assert fake_default_application.probe_calls == 1
    assert fake_default_application.aclose_calls == 1


async def test_run_shutdown_closes_only_built_application(
    fake_default_application: _FakeApplication,
) -> None:
    await run_shutdown()
    assert fake_default_application.aclose_calls == 1

    set_default_application(None)
    await run_shutdown()
    assert fake_default_application.aclose_calls == 1
