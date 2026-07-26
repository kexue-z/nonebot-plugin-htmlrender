"""Typed execution boundary for HTMLKit rc5."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, final

import anyio

from nonebot_plugin_htmlrender.preparation.models import RenderRequirement
from nonebot_plugin_htmlrender.providers.sdk import HTMLKIT_PROVIDER_ID
from nonebot_plugin_htmlrender.rendering.artifacts import RenderedImage
from nonebot_plugin_htmlrender.rendering.errors import (
    ProviderExecutionError,
    ProviderUnavailable,
    RenderingError,
    UnsupportedRenderOption,
    UnsupportedRequirement,
)
from nonebot_plugin_htmlrender.rendering.observers import observe_operation
from nonebot_plugin_htmlrender.rendering.requests import (
    effective_resource_resolve_mode,
)

from .api import HtmlkitAPI, load_htmlkit_api
from .document import build_htmlkit_document

if TYPE_CHECKING:
    from collections.abc import Coroutine, Iterator

    from nonebot_plugin_htmlrender.preparation.models import (
        PreparedHtml,
        RasterOptions,
    )
    from nonebot_plugin_htmlrender.rendering.ports import OperationObserver
    from nonebot_plugin_htmlrender.rendering.requests import ResourcePolicy
    from nonebot_plugin_htmlrender.resources.ports import ProviderResources

    from .config import HtmlkitConfig

_OBSERVATION_ATTRIBUTES: dict[str, str] = {"render.backend": HTMLKIT_PROVIDER_ID}
_ASYNCIO_ONLY_MESSAGE = (
    "HTMLKit 0.1.0rc5 is asyncio-only and cannot run under the current "
    "asynchronous backend."
)
_PROBE_HTML = '<div style="width:1px;height:1px"></div>'


def ensure_htmlkit_asyncio() -> asyncio.AbstractEventLoop:
    """Return the loop required by upstream or raise a stable domain error."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError as error:
        raise ProviderUnavailable(_ASYNCIO_ONLY_MESSAGE, source=error) from error


def _validate_options(options: RasterOptions) -> None:
    if options.device_pixel_ratio != 1.0:
        raise UnsupportedRenderOption(
            "HTMLKit 0.1.0rc5 cannot represent RasterOptions.device_pixel_ratio; "
            "set device_pixel_ratio=1.0."
        )
    if options.height is not None:
        raise UnsupportedRenderOption(
            "HTMLKit 0.1.0rc5 cannot represent an explicit RasterOptions.height; "
            "use content-driven height (height=None)."
        )


def _validate_document(prepared: PreparedHtml) -> None:
    if RenderRequirement.JAVASCRIPT in prepared.requirements:
        raise UnsupportedRequirement(
            "HTMLKit uses litehtml and cannot execute JavaScript."
        )


@contextmanager
def _translate(operation: str) -> Iterator[None]:
    try:
        yield
    except RenderingError:
        raise
    except Exception as error:
        raise ProviderExecutionError(
            f"HTMLKit {operation} failed.",
            source=error,
        ) from error


async def _await_native(coroutine: Coroutine[object, object, bytes]) -> bytes:
    """Shield and drain upstream's detached native thread before cancellation.

    HTMLKit cannot cancel the native render.  Releasing the application gate,
    resource reader, or concurrency token while its callbacks are still live
    would create a use-after-close race, so cancellation is propagated only
    after the native future reaches a terminal state.
    """
    task = asyncio.create_task(coroutine)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        if error := await _await_shielded_once(task):
            # Repeated Task.cancel() calls and AnyIO level cancellation must
            # never reach the upstream Future.  Remember the latest request,
            # then keep shielding until the detached native thread completes.
            cancellation = error

    if cancellation is not None:
        with suppress(BaseException):
            task.result()
        raise cancellation
    return task.result()


async def _await_shielded_once(
    task: asyncio.Task[bytes],
) -> asyncio.CancelledError | None:
    """Wait for one shielded checkpoint without cancelling native work."""
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError as error:
        if task.cancelled():
            raise
        return error
    return None


@final
class HtmlkitExecutor:
    """Execute prepared HTML through a bounded HTMLKit native thread budget."""

    def __init__(
        self,
        *,
        config: HtmlkitConfig,
        resources: ProviderResources,
        observer: OperationObserver,
    ) -> None:
        self._config = config.model_copy(deep=True)
        self._resources = resources
        self._observer = observer
        self._slots = anyio.Semaphore(config.max_concurrency)
        self._api: HtmlkitAPI | None = None

    def _load_api(self) -> HtmlkitAPI:
        api = self._api
        if api is None:
            api = load_htmlkit_api()
            self._api = api
        return api

    async def execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        *,
        resource_policy: ResourcePolicy | None = None,
        timeout_seconds: float | None = None,
    ) -> RenderedImage:
        ensure_htmlkit_asyncio()
        _validate_document(prepared)
        _validate_options(options)
        if timeout_seconds is None:
            return await self._execute(prepared, options, resource_policy)
        try:
            with anyio.fail_after(timeout_seconds):
                return await self._execute(prepared, options, resource_policy)
        except TimeoutError as error:
            raise ProviderExecutionError(
                f"Render operation timed out after {timeout_seconds} seconds.",
                source=error,
            ) from error

    async def _execute(
        self,
        prepared: PreparedHtml,
        options: RasterOptions,
        resource_policy: ResourcePolicy | None,
    ) -> RenderedImage:
        resolve_mode = effective_resource_resolve_mode(
            resource_policy,
            self._resources.strategy.resolve_mode,
        )
        document = await build_htmlkit_document(
            prepared,
            resources=self._resources,
            resolve_mode=resolve_mode,
        )
        async with self._slots:
            with (
                observe_operation(
                    self._observer,
                    "htmlkit.rasterize_html",
                    {
                        **_OBSERVATION_ATTRIBUTES,
                        "render.format": options.format,
                    },
                ),
                _translate("render"),
            ):
                data = await _await_native(
                    self._load_api().html_to_pic(
                        document.html,
                        base_url=document.base_url,
                        dpi=self._config.media_dpi,
                        max_width=float(options.width),
                        device_height=self._config.media_height,
                        default_font_size=self._config.default_font_size,
                        font_name=self._config.font_name,
                        allow_refit=False,
                        image_format=options.format,
                        jpeg_quality=(
                            options.quality if options.quality is not None else 100
                        ),
                        lang=self._config.language,
                        culture=self._config.culture,
                        img_fetch_fn=document.resources.fetch_image,
                        css_fetch_fn=document.resources.fetch_stylesheet,
                        native_data_scheme=True,
                    )
                )
                document.resources.raise_callback_error()
                return RenderedImage.from_bytes(
                    data,
                    expected_format=options.format,
                )


@final
class HtmlkitLifecycle:
    """Validate the asyncio host and provide a real native readiness probe."""

    def __init__(self, executor: HtmlkitExecutor) -> None:
        self._executor = executor

    async def startup(self) -> None:
        ensure_htmlkit_asyncio()

    async def probe(self) -> None:
        from nonebot_plugin_htmlrender.preparation import (  # noqa: PLC0415
            RasterOptions,
            prepare_html,
        )

        await self._executor.execute(
            prepare_html(_PROBE_HTML),
            RasterOptions(
                width=8,
                height=None,
                device_pixel_ratio=1.0,
            ),
        )

    async def aclose(self) -> None:
        return None


__all__ = ["HtmlkitExecutor", "HtmlkitLifecycle", "ensure_htmlkit_asyncio"]
