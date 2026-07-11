"""The shipped example provider must keep satisfying the SDK contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import TYPE_CHECKING

import pytest

from nonebot_plugin_htmlrender.bootstrap.composition import prepare_runtime
from nonebot_plugin_htmlrender.bootstrap.settings import RenderSettings
from nonebot_plugin_htmlrender.providers.sdk import EngineProvider
from nonebot_plugin_htmlrender.rendering import RenderHtmlRequest
from nonebot_plugin_htmlrender.resources.config import (
    get_resource_config,
    register_resource_config_provider,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_EXAMPLE_MODULE = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "echo-provider"
    / "src"
    / "htmlrender_echo_provider"
    / "__init__.py"
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def _restore_resource_config() -> Iterator[None]:
    previous = register_resource_config_provider(None)
    register_resource_config_provider(previous)
    yield
    register_resource_config_provider(previous)


def _load_example_provider() -> EngineProvider:
    spec = importlib.util.spec_from_file_location(
        "htmlrender_echo_provider",
        _EXAMPLE_MODULE,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass processing resolves string annotations through sys.modules.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        provider = module.PROVIDER
    finally:
        sys.modules.pop(spec.name, None)
    assert isinstance(provider, EngineProvider)
    return provider


async def test_echo_provider_composes_and_renders() -> None:
    provider = _load_example_provider()
    settings = RenderSettings.model_validate(
        {
            "provider": "echo",
            "provider_config": {"color": "#ff0000"},
        }
    )

    runtime = prepare_runtime(settings, explicit_providers=[provider])
    application = runtime.build_application()
    await application.startup()
    try:
        artifact = await application.renderer.render_html(
            RenderHtmlRequest(html="<p>echo</p>")
        )
    finally:
        await application.aclose()

    payload = bytes(artifact)
    assert payload[: len(_PNG_MAGIC)] == _PNG_MAGIC
    assert get_resource_config() is not None
