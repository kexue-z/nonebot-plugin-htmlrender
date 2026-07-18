from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from nonebot_plugin_htmlrender.adapters.takumi import (
    TakumiConfig,
    TakumiExtension,
)
from nonebot_plugin_htmlrender.adapters.takumi.render import (
    takumi_availability,
)
from nonebot_plugin_htmlrender.adapters.takumi.runtime import TakumiRuntimeState
from nonebot_plugin_htmlrender.capabilities import TAKUMI_CAPABILITIES, TakumiCapability
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
        limiter=anyio.CapacityLimiter(1),
        config=TakumiConfig(),
        resources=resource_service(),
    )


def test_capability_key_identity() -> None:
    assert TAKUMI_CAPABILITIES.name == "takumi.capabilities"
    assert TAKUMI_CAPABILITIES.interface is TakumiCapability


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
        "nonebot_plugin_htmlrender.adapters.takumi.render.find_spec",
        return_value=object() if located else None,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.adapters.takumi.render.version",
        return_value=installed_version,
    )
    status = takumi_availability()
    assert status.available is available
    if reason is not None:
        assert reason in (status.reason or "")


async def test_extension_telemetry_covers_success_and_error_without_content(
    mocker: MockerFixture,
    operation_observer: RecordingOperationObserver,
) -> None:
    extension = TakumiExtension(_state(), operation_observer)
    assert (
        await extension.render_node(
            {"type": "container"},
            width=10,
            height=10,
        )
        == b"node"
    )
    assert operation_observer.operations[-1] == (
        "takumi.extension.render_node",
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
        await TakumiExtension(state, operation_observer).render_svg_node(
            {"type": "container"},
            width=10,
            height=10,
        )
    assert operation_observer.operations[-1] == (
        "takumi.extension.render_svg_node",
        {"render.backend": "takumi"},
        "error",
    )
