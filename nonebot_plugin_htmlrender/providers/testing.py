"""NoneBot-hosted conformance harness for third-party engine providers.

The harness ships with the production package so provider authors can run the
same lifecycle checks from an installed wheel after initializing NoneBot and
loading ``nonebot_plugin_htmlrender``. It has no test-runner dependency:
callers wrap the coroutines in pytest, unittest, or another runner. Violations raise
:class:`ProviderConformanceError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot_plugin_htmlrender.bootstrap.composition import prepare_runtime
from nonebot_plugin_htmlrender.rendering import (
    ProviderLifecycleError,
    RenderedImage,
    RenderHtmlRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot_plugin_htmlrender.bootstrap.settings import RenderSettings
    from nonebot_plugin_htmlrender.providers.sdk import EngineProvider


class ProviderConformanceError(AssertionError):
    """A provider violated the documented lifecycle contract."""


def _require(*, condition: bool, message: str) -> None:
    if not condition:
        raise ProviderConformanceError(message)


async def run_provider_lifecycle_conformance(
    provider: EngineProvider[Any],
    settings: RenderSettings,
) -> None:
    """Exercise the fault-free lifecycle invariants of one provider.

    Covers: compose produces an application without performing I/O; startup,
    probe and aclose are each idempotent; a rendered artifact is typed; and a
    closed application rejects a fresh startup.
    """
    runtime = prepare_runtime(settings, explicit_providers=[provider])

    # compose is I/O-free: building the application must not require startup.
    application = runtime.build_application()

    # Idempotent startup.
    await application.startup()
    await application.startup()

    # Probe does not change ownership and can be repeated.
    await application.probe()
    await application.probe()

    artifact = await application.renderer.render_html(
        RenderHtmlRequest(html="<p>conformance</p>")
    )
    _require(
        condition=isinstance(artifact, RenderedImage),
        message="render_html must return a typed RenderedImage artifact",
    )
    _require(
        condition=bool(bytes(artifact)),
        message="the rendered artifact must carry bytes",
    )

    # Idempotent shutdown.
    await application.aclose()
    await application.aclose()

    # A closed application refuses to start again.
    try:
        await application.startup()
    except ProviderLifecycleError:
        return
    raise ProviderConformanceError(
        "a closed application must reject a fresh startup with ProviderLifecycleError"
    )


async def run_provider_startup_retry_conformance(
    provider: EngineProvider[Any],
    settings: RenderSettings,
    *,
    fail_once: Callable[[], None],
) -> None:
    """Assert startup is retryable after a single transient failure.

    ``fail_once`` is a callable the caller uses to arm a one-shot failure in
    the provider's runtime before the first startup; after the failed startup
    a second startup must succeed.
    """
    runtime = prepare_runtime(settings, explicit_providers=[provider])
    application = runtime.build_application()

    fail_once()
    try:
        await application.startup()
    except Exception:  # noqa: S110 -- provider-defined error type
        pass
    else:
        raise ProviderConformanceError(
            "the armed one-shot startup failure did not surface"
        )

    try:
        await application.startup()
        await application.renderer.render_html(RenderHtmlRequest(html="<p>ok</p>"))
    finally:
        await application.aclose()


__all__ = [
    "ProviderConformanceError",
    "run_provider_lifecycle_conformance",
    "run_provider_startup_retry_conformance",
]
