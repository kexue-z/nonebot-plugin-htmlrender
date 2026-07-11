from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any, TypeVar, cast

from nonebot_plugin_htmlrender.backend import (
    BackendCapability,
    BackendExtension,
    RenderRuntime,
    RenderSession,
)
from nonebot_plugin_htmlrender.backend.factory import (
    BackendAvailability,
    register_backend,
)
from nonebot_plugin_htmlrender.consts import RenderBackend
from nonebot_plugin_htmlrender.utils import track_render

from . import operations
from .api import TAKUMI_EXTENSION, TakumiExtension
from .config import get_takumi_config
from .errors import TakumiRuntimeError, TakumiUnsupportedError
from .runtime import (
    create_runtime_state,
    require_runtime_state,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot_plugin_htmlrender.preparation import PreparedHtml, RasterOptions

    from .operations import (
        HtmlRenderRequestLike,
        TemplateConfigLike,
        TemplateRenderRequestLike,
    )

ExtensionT = TypeVar("ExtensionT")
_SUPPORTED_TAKUMI_VERSION = "0.2.0"


async def _noop_close() -> None:
    return None


class TakumiBackend:
    """Process-local Rust-backed renderer exposed through async worker calls."""

    backend: RenderBackend = RenderBackend.TAKUMI
    capabilities = frozenset(
        {
            BackendCapability.HTML_RENDER,
            BackendCapability.HTML_RASTERIZE,
            BackendCapability.TEXT_RENDER,
            BackendCapability.MARKDOWN_RENDER,
            BackendCapability.TEMPLATE_RENDER,
            BackendCapability.TEMPLATE_HTML_RENDER,
        }
    )

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        return ()

    async def create_runtime(self) -> RenderRuntime:
        async with track_render("takumi.open_runtime", backend=self.backend):
            state = await create_runtime_state(get_takumi_config())

            async def _aclose() -> None:
                async with track_render("takumi.close_runtime", backend=self.backend):
                    await state.aclose()

            return RenderRuntime(
                backend=self.backend,
                handle=state,
                _aclose=_aclose,
            )

    async def create_session(
        self,
        runtime: RenderRuntime,
        **kwargs: Any,
    ) -> RenderSession:
        async with track_render("takumi.open_session", backend=self.backend):
            unsupported = sorted(
                key for key, value in kwargs.items() if value is not None
            )
            if unsupported:
                raise TakumiUnsupportedError(
                    "Takumi has no browser session options; unsupported options: "
                    f"{', '.join(unsupported)}."
                )
            if runtime.backend is not self.backend:
                raise TypeError(
                    f"Expected a {self.backend.value} runtime, "
                    f"got {runtime.backend.value}."
                )
            state = require_runtime_state(runtime.handle)

            async def _close_session() -> None:
                async with track_render(
                    "takumi.close_session",
                    backend=self.backend,
                ):
                    await _noop_close()

            return RenderSession(
                runtime=runtime,
                handle=state,
                _aclose=_close_session,
            )

    def is_alive(self, session: RenderSession) -> bool:
        if (
            session.runtime.backend is not self.backend
            or session.handle is not session.runtime.handle
        ):
            return False
        try:
            require_runtime_state(session.handle)
        except TakumiRuntimeError:
            return False
        return True

    def get_extension(
        self,
        session: RenderSession,
        extension: BackendExtension[ExtensionT],
    ) -> ExtensionT | None:
        if extension is not TAKUMI_EXTENSION:
            return None
        state = require_runtime_state(session.handle)
        return cast("ExtensionT", TakumiExtension(state))

    async def rasterize_html(
        self,
        session: RenderSession,
        prepared: PreparedHtml,
        options: RasterOptions,
    ) -> bytes:
        async with track_render("takumi.rasterize_html", backend=self.backend):
            state = require_runtime_state(session.handle)
            return await operations.rasterize_html(state, prepared, options)

    async def render_html(
        self,
        session: RenderSession,
        request: HtmlRenderRequestLike | str,
        **kwargs: Any,
    ) -> bytes:
        async with track_render("takumi.render_html", backend=self.backend):
            state = require_runtime_state(session.handle)
            return await operations.render_html(state, request, **kwargs)

    async def render_text(
        self,
        session: RenderSession,
        text: str,
        **kwargs: Any,
    ) -> bytes:
        async with track_render("takumi.render_text", backend=self.backend):
            state = require_runtime_state(session.handle)
            return await operations.render_text(state, text, **kwargs)

    async def render_markdown(
        self,
        session: RenderSession,
        markdown_text: str = "",
        **kwargs: Any,
    ) -> bytes:
        async with track_render("takumi.render_markdown", backend=self.backend):
            state = require_runtime_state(session.handle)
            return await operations.render_markdown(
                state,
                markdown_text,
                **kwargs,
            )

    async def render_template(
        self,
        session: RenderSession,
        request: TemplateRenderRequestLike | str,
        **kwargs: Any,
    ) -> bytes:
        async with track_render("takumi.render_template", backend=self.backend):
            state = require_runtime_state(session.handle)
            return await operations.render_template(state, request, **kwargs)

    async def render_template_html(
        self,
        template: TemplateConfigLike | str,
        **kwargs: Any,
    ) -> str:
        async with track_render("takumi.render_template_html", backend=self.backend):
            return await operations.render_template_html(template, **kwargs)


def is_takumi_backend_available() -> BackendAvailability:
    try:
        if find_spec("takumi_py") is None:
            return BackendAvailability(
                available=False,
                reason="Optional dependency `takumi-py==0.2.0` is not installed.",
            )
    except (ImportError, ValueError) as error:
        return BackendAvailability(
            available=False,
            reason=f"Cannot locate takumi_py: {error}",
        )

    try:
        installed_version = version("takumi-py")
    except PackageNotFoundError:
        return BackendAvailability(
            available=False,
            reason="Distribution metadata for `takumi-py` is unavailable.",
        )
    if installed_version != _SUPPORTED_TAKUMI_VERSION:
        return BackendAvailability(
            available=False,
            reason=(
                f"Unsupported takumi-py version {installed_version!r}; "
                f"expected {_SUPPORTED_TAKUMI_VERSION!r}."
            ),
        )

    return BackendAvailability(available=True)


def register_takumi_backend() -> None:
    register_backend(
        RenderBackend.TAKUMI,
        TakumiBackend,
        availability_checker=is_takumi_backend_available,
    )


register_takumi_backend()


__all__ = [
    "TakumiBackend",
    "is_takumi_backend_available",
    "register_takumi_backend",
]
