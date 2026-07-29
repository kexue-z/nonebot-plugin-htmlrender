from __future__ import annotations

import struct

import pytest

takumi_py = pytest.importorskip("takumi_py")

from nonebot_plugin_htmlrender.adapters.takumi import TakumiConfig, TakumiRuntimeError
from nonebot_plugin_htmlrender.adapters.takumi.api import TakumiAPIAdapter
from nonebot_plugin_htmlrender.adapters.takumi.runtime import create_runtime_state
from tests.adapters.takumi.helpers import resource_service


async def test_takumi_native_boundary_renders_extension_output() -> None:
    state = await create_runtime_state(TakumiConfig(), resources=resource_service())
    try:
        rendered = await TakumiAPIAdapter(state).render_html(
            '<div style="width:32px;height:16px;background:#00f"></div>',
            width=32,
            height=16,
            device_pixel_ratio=2,
        )
    finally:
        await state.aclose()

    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", rendered[16:24]) == (64, 32)


async def test_takumi_exact_native_methods_use_projected_signatures() -> None:
    state = await create_runtime_state(TakumiConfig(), resources=resource_service())
    try:
        api = TakumiAPIAdapter(state)
        node = await api.compile_node({"type": "container"}, validate=True)
        keyframes = await api.compile_keyframes(
            {
                "fade": {
                    "from": {"opacity": 0},
                    "to": {"opacity": 1},
                }
            }
        )
    finally:
        await state.aclose()

    assert isinstance(node, takumi_py.CompiledNode)
    assert isinstance(keyframes, takumi_py.CompiledStyleSheet)


async def test_takumi_native_error_is_translated_at_runtime_boundary() -> None:
    state = await create_runtime_state(TakumiConfig(), resources=resource_service())
    try:
        with pytest.raises(TakumiRuntimeError, match="compile") as raised:
            await state.compile_stylesheet("}", lossy=False)
    finally:
        await state.aclose()

    assert isinstance(raised.value.__cause__, takumi_py.StyleSheetError)
