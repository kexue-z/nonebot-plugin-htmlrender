from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import pytest

from nonebot_plugin_htmlrender.backend import BackendCapability, BackendExtension
from nonebot_plugin_htmlrender.backend.takumi import (
    TAKUMI_EXTENSION,
    TakumiConfig,
    TakumiExtension,
    TakumiUnsupportedError,
)
from nonebot_plugin_htmlrender.backend.takumi.render import (
    TakumiBackend,
    is_takumi_backend_available,
)
from nonebot_plugin_htmlrender.backend.takumi.runtime import TakumiRuntimeState
from nonebot_plugin_htmlrender.consts import RenderBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.backend.takumi.types import NativeRenderer


class _Renderer:
    def render_node(self, node: object, **kwargs: object) -> bytes:
        del node, kwargs
        return b"node"


def _state() -> TakumiRuntimeState:
    import anyio  # noqa: PLC0415

    return TakumiRuntimeState(
        renderer=cast("NativeRenderer", _Renderer()),
        limiter=anyio.CapacityLimiter(1),
        config=TakumiConfig(),
    )


def test_capability_set_exposes_common_features_without_element_capture() -> None:
    capabilities = TakumiBackend.capabilities
    assert capabilities == frozenset(
        {
            BackendCapability.HTML_RENDER,
            BackendCapability.HTML_RASTERIZE,
            BackendCapability.TEXT_RENDER,
            BackendCapability.MARKDOWN_RENDER,
            BackendCapability.TEMPLATE_RENDER,
            BackendCapability.TEMPLATE_HTML_RENDER,
        }
    )
    assert BackendCapability.HTML_ELEMENT_CAPTURE not in capabilities


@pytest.mark.anyio
async def test_runtime_session_context_and_typed_extension(
    mocker: MockerFixture,
) -> None:
    state = _state()
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.render.get_takumi_config",
        return_value=TakumiConfig(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.render.create_runtime_state",
        new=mocker.AsyncMock(return_value=state),
    )
    backend = TakumiBackend()
    runtime = await backend.create_runtime()
    session = await backend.create_session(runtime)

    assert backend.is_alive(session)
    extension = backend.get_extension(session, TAKUMI_EXTENSION)
    assert isinstance(extension, TakumiExtension)
    assert extension._state is state
    assert (
        backend.get_extension(
            session,
            BackendExtension("unknown", object),
        )
        is None
    )

    with pytest.raises(TakumiUnsupportedError, match="session options"):
        await backend.create_session(runtime, endpoint="ws://browser")

    await runtime.aclose()
    assert not backend.is_alive(session)


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
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.render.find_spec",
        return_value=object() if located else None,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.render.version",
        return_value=installed_version,
    )
    status = is_takumi_backend_available()
    assert status.available is available
    if reason is not None:
        assert reason in (status.reason or "")


@pytest.mark.anyio
async def test_extension_telemetry_covers_success_and_error_without_content(
    mocker: MockerFixture,
) -> None:
    events: list[tuple[str, str, object]] = []

    @asynccontextmanager
    async def fake_track(
        op: str,
        *,
        backend: RenderBackend,
        **kwargs: Any,
    ) -> AsyncIterator[None]:
        events.append(("enter", op, backend))
        assert kwargs == {}
        try:
            yield
        except Exception as error:
            events.append(("error", op, type(error)))
            raise
        finally:
            events.append(("exit", op, backend))

    mocker.patch(
        "nonebot_plugin_htmlrender.backend.takumi.api.track_render",
        side_effect=fake_track,
    )
    extension = TakumiExtension(_state())
    assert (
        await extension.render_node(
            {"type": "container"},
            width=10,
            height=10,
        )
        == b"node"
    )
    assert events[:2] == [
        ("enter", "takumi.extension.render_node", RenderBackend.TAKUMI),
        ("exit", "takumi.extension.render_node", RenderBackend.TAKUMI),
    ]

    error = ValueError("native failure")
    state = _state()
    mocker.patch.object(
        TakumiRuntimeState,
        "call_renderer",
        new=mocker.AsyncMock(side_effect=error),
    )
    with pytest.raises(ValueError, match="native failure"):
        await TakumiExtension(state).render_svg_node(
            {"type": "container"},
            width=10,
            height=10,
        )
    assert events[-3:] == [
        ("enter", "takumi.extension.render_svg_node", RenderBackend.TAKUMI),
        ("error", "takumi.extension.render_svg_node", ValueError),
        ("exit", "takumi.extension.render_svg_node", RenderBackend.TAKUMI),
    ]
