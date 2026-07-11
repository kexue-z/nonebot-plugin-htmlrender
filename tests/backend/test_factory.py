from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.backend import factory
from nonebot_plugin_htmlrender.backend.base import (
    BackendCapability,
    RenderRuntime,
    RenderSession,
)
from nonebot_plugin_htmlrender.backend.factory import BackendAvailability
from nonebot_plugin_htmlrender.consts import RenderBackend

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator

    from pytest_mock import MockerFixture


@pytest.fixture
def isolated_backend_registry() -> Generator[None, None, None]:
    previous = dict(factory._backend_registry)
    previous_loaders = dict(factory._backend_loaders)
    factory._backend_registry.clear()
    factory._backend_loaders.clear()
    try:
        yield
    finally:
        factory._backend_registry.clear()
        factory._backend_registry.update(previous)
        factory._backend_loaders.clear()
        factory._backend_loaders.update(previous_loaders)


class _DummyBackend:
    def __init__(self, backend: RenderBackend, marker: object) -> None:
        self.backend = backend
        self.marker = marker
        self.capabilities = frozenset({BackendCapability.RENDER_CONTEXT})

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        return ()

    async def create_runtime(self) -> RenderRuntime:
        async def _close_runtime() -> None:
            return None

        return RenderRuntime(
            backend=self.backend,
            handle=object(),
            _aclose=_close_runtime,
        )

    async def create_session(
        self,
        runtime: RenderRuntime,
        **kwargs: object,  # noqa: ARG002
    ) -> RenderSession:
        async def _close_session() -> None:
            return None

        return RenderSession(
            runtime=runtime,
            handle=object(),
            _aclose=_close_session,
        )

    def is_alive(self, session: RenderSession) -> bool:  # noqa: ARG002
        return True

    @asynccontextmanager
    async def get_render_context(
        self,
        session: RenderSession,  # noqa: ARG002
        **kwargs: object,  # noqa: ARG002
    ):
        yield object()


def test_register_and_query_backend_status(isolated_backend_registry: None) -> None:
    del isolated_backend_registry

    backend_object = _DummyBackend(RenderBackend.PLAYWRIGHT, marker="singleton")
    factory.register_backend(
        RenderBackend.PLAYWRIGHT,
        lambda: backend_object,
    )

    assert factory.is_backend_registered(RenderBackend.PLAYWRIGHT) is True
    assert factory.registered_backends() == (RenderBackend.PLAYWRIGHT,)
    assert factory.get_backend_status(RenderBackend.PLAYWRIGHT).available is True
    assert factory._backend_registry[RenderBackend.PLAYWRIGHT].builder() is (
        backend_object
    )


def test_register_backend_conflict_and_force_override(
    isolated_backend_registry: None,
) -> None:
    del isolated_backend_registry

    factory.register_backend(
        RenderBackend.PLAYWRIGHT,
        lambda: _DummyBackend(RenderBackend.PLAYWRIGHT, marker="first"),
    )

    with pytest.raises(RuntimeError, match="already registered"):
        factory.register_backend(
            RenderBackend.PLAYWRIGHT,
            lambda: _DummyBackend(RenderBackend.PLAYWRIGHT, marker="second"),
        )

    factory.register_backend(
        RenderBackend.PLAYWRIGHT,
        lambda: _DummyBackend(RenderBackend.PLAYWRIGHT, marker="second"),
        force=True,
    )
    built = factory._backend_registry[RenderBackend.PLAYWRIGHT].builder()
    assert isinstance(built, _DummyBackend)
    assert built.marker == "second"


def test_get_backend_status_handles_unregistered_and_checker_failure(
    isolated_backend_registry: None,
) -> None:
    del isolated_backend_registry

    status = factory.get_backend_status(RenderBackend.SKIA)
    assert status.registered is False
    assert status.available is False
    assert "not registered" in (status.reason or "")

    def _build_backend() -> _DummyBackend:
        return _DummyBackend(RenderBackend.PLAYWRIGHT, marker="status")

    def _broken_checker() -> BackendAvailability:
        raise RuntimeError("boom")

    factory.register_backend(
        RenderBackend.PLAYWRIGHT,
        _build_backend,
        availability_checker=_broken_checker,
    )
    failed_status = factory.get_backend_status(RenderBackend.PLAYWRIGHT)
    assert failed_status.registered is True
    assert failed_status.available is False
    assert "Availability check failed" in (failed_status.reason or "")


def test_available_and_unavailable_backends(isolated_backend_registry: None) -> None:
    del isolated_backend_registry

    def _build_playwright() -> _DummyBackend:
        return _DummyBackend(RenderBackend.PLAYWRIGHT, marker="playwright")

    def _build_skia() -> _DummyBackend:
        return _DummyBackend(RenderBackend.SKIA, marker="skia")

    factory.register_backend(
        RenderBackend.PLAYWRIGHT,
        _build_playwright,
        availability_checker=lambda: BackendAvailability(available=True),
    )
    factory.register_backend(
        RenderBackend.SKIA,
        _build_skia,
        availability_checker=lambda: BackendAvailability(
            available=False, reason="no engine"
        ),
    )

    assert factory.available_backends() == (RenderBackend.PLAYWRIGHT,)
    assert RenderBackend.SKIA in factory.unavailable_backends()
    assert factory.is_backend_available(RenderBackend.SKIA) is False


def test_get_backend_status_loads_known_backend(
    isolated_backend_registry: None,
    mocker: MockerFixture,
) -> None:
    del isolated_backend_registry

    def _register_backend() -> None:
        factory.register_backend(
            RenderBackend.PLAYWRIGHT,
            lambda: _DummyBackend(RenderBackend.PLAYWRIGHT, marker="status"),
        )

    fake_module = SimpleNamespace(register_fake_backend=_register_backend)
    mocker.patch.dict(
        factory._backend_loaders,
        {RenderBackend.PLAYWRIGHT: ("fake_backend", "register_fake_backend")},
        clear=True,
    )
    mocker.patch.object(factory, "import_module", return_value=fake_module)

    status = factory.get_backend_status(RenderBackend.PLAYWRIGHT)

    assert status.registered is True
    assert status.available is True


def test_get_backend_status_does_not_load_unknown_backend(
    isolated_backend_registry: None,
    mocker: MockerFixture,
) -> None:
    del isolated_backend_registry

    import_module = mocker.patch.object(factory, "import_module")

    status = factory.get_backend_status(RenderBackend.SKIA)

    import_module.assert_not_called()
    assert status.registered is False
    assert status.available is False


def test_backend_statuses_cover_all_enum_values(
    isolated_backend_registry: None,
    mocker: MockerFixture,
) -> None:
    del isolated_backend_registry

    mocker.patch.dict(factory._backend_loaders, {}, clear=True)
    statuses = factory.backend_statuses()
    assert len(statuses) == len(tuple(RenderBackend))
    assert all(status.backend in RenderBackend for status in statuses)
    assert all(status.registered is False for status in statuses)
