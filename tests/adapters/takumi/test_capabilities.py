"""Takumi access contract and managed API observation tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender.adapters.takumi import (
    TakumiAPIAdapter,
    TakumiConfig,
)
from nonebot_plugin_htmlrender.adapters.takumi.runtime import TakumiRuntimeState
from nonebot_plugin_htmlrender.capabilities import (
    TAKUMI,
    TakumiAccess,
)
from tests.adapters.takumi.helpers import resource_service

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from nonebot_plugin_htmlrender.adapters.takumi.types import NativeRenderer
    from tests.adapters.conftest import RecordingOperationObserver


class _Renderer:
    def render_node(self, node: object, **kwargs: object) -> bytes:
        del node, kwargs
        return b"node"


def _state() -> TakumiRuntimeState:
    import anyio  # noqa: PLC0415

    return TakumiRuntimeState(
        renderer=cast("NativeRenderer", _Renderer()),
        limiter=anyio.Semaphore(1),
        config=TakumiConfig(),
        resources=resource_service(),
    )


def test_takumi_capability_key_identity() -> None:
    assert TAKUMI.name == "takumi"
    assert TAKUMI.interface is TakumiAccess


async def test_managed_api_telemetry_covers_success_and_error_without_content(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    api = TakumiAPIAdapter(_state(), operation_observer)
    assert (
        await api.render_node(
            {"type": "container"},
            width=10,
            height=10,
        )
        == b"node"
    )
    assert operation_observer.operations[-1] == (
        "takumi.api.render_node",
        {"render.backend": "takumi"},
        "success",
    )

    error = ValueError("native failure")
    state = _state()
    mocker.patch.object(
        TakumiRuntimeState,
        "call_renderer",
        new=mocker.AsyncMock(side_effect=error),
    )
    with pytest.raises(ValueError, match="native failure"):
        await TakumiAPIAdapter(state, operation_observer).render_svg_node(
            {"type": "container"},
            width=10,
            height=10,
        )
    assert operation_observer.operations[-1] == (
        "takumi.api.render_svg_node",
        {"render.backend": "takumi"},
        "error",
    )
