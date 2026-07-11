from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Generic,
    Protocol,
    TypeVar,
)
from typing_extensions import Self

if TYPE_CHECKING:
    from contextlib import AsyncExitStack
    from types import TracebackType

    from nonebot_plugin_htmlrender.consts import RenderBackend


class StrEnum(str, Enum):
    """字符串枚举基类，用于声明取值为字符串的枚举类型。"""


class BackendCapability(StrEnum):
    """Low-level capabilities exposed by a backend implementation.

    These values describe what a concrete backend can provide internally.
    They are backend-facing building blocks, not necessarily the final
    user-facing API surface.
    """

    RENDER_CONTEXT = "render_context"
    """The backend can create a render context for one render operation."""

    HTML_RENDER = "html_render"
    """The backend can render HTML/CSS content using web-engine semantics."""

    TEXT_RENDER = "text_render"
    """The backend can render plain text into image output."""

    MARKDOWN_RENDER = "markdown_render"
    """The backend can render Markdown content into image output."""

    TEMPLATE_RENDER = "template_render"
    """The backend can render template content into image output."""

    TEMPLATE_HTML_RENDER = "template_html_render"
    """The backend can render template content into raw HTML output."""

    HTML_ELEMENT_CAPTURE = "html_element_capture"
    """The backend can capture a specific HTML element into image output."""

    RASTER_RENDER = "raster_render"
    """The backend can draw raster output from backend-specific inputs."""

    HTML_RASTERIZE = "html_rasterize"
    """The backend can execute a prepared HTML document into raster output."""


@dataclass(slots=True)
class RenderRuntime:
    """后端运行时句柄。

    持有由后端创建的进程级资源（如 Playwright 实例），并通过 ``_aclose``
    回调封装关闭逻辑，便于交给 ``AsyncExitStack`` 统一管理。
    """

    backend: RenderBackend
    handle: object
    _aclose: Callable[[], Awaitable[None]]

    def attach(self, stack: AsyncExitStack) -> None:  # pragma: no cover
        """将运行时的关闭回调注册到 AsyncExitStack。"""
        stack.push_async_callback(self.aclose)

    async def aclose(self) -> None:
        """关闭运行时并释放资源。"""
        await self._aclose()

    async def __aenter__(self) -> Self:  # pragma: no cover
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:  # pragma: no cover
        await self.aclose()


@dataclass(slots=True)
class RenderSession:
    """绑定到 ``RenderRuntime`` 的渲染会话。

    会话表示一次连续渲染所需的浏览器上下文等资源，可与运行时协同管理生命周期。
    """

    runtime: RenderRuntime
    handle: object
    _aclose: Callable[[], Awaitable[None]]

    def attach(self, stack: AsyncExitStack) -> None:  # pragma: no cover
        """将会话的关闭回调注册到 AsyncExitStack。"""
        stack.push_async_callback(self.aclose)

    async def aclose(self) -> None:
        """关闭会话并释放资源。"""
        await self._aclose()

    async def __aenter__(self) -> Self:  # pragma: no cover
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:  # pragma: no cover
        await self.aclose()


class Backend(Protocol):
    backend: RenderBackend
    capabilities: frozenset[BackendCapability]

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        """Ordered async steps to prepare backend before open_runtime()."""
        return ()

    async def create_runtime(self) -> RenderRuntime:
        """Create backend-scoped resources.

        Caller may attach the returned runtime to an AsyncExitStack, or close manually.
        """
        ...

    async def create_session(
        self,
        runtime: RenderRuntime,
        **kwargs: Any,
    ) -> RenderSession:
        """Create task-scoped resources bound to the given runtime.

        Caller may attach the returned session to an AsyncExitStack, or close manually.
        """
        ...

    def is_alive(self, session: RenderSession) -> bool:
        """检查渲染会话是否仍然存活。"""
        ...


ExtensionT = TypeVar("ExtensionT")


@dataclass(frozen=True, slots=True)
class BackendExtension(Generic[ExtensionT]):
    """Typed token used to discover an optional backend-specific service."""

    name: str
    interface: type[ExtensionT]


@dataclass(frozen=True)
class BackendAvailability:
    """后端运行环境检测结果。

    Attributes:
        available: 当前环境是否可用此后端。
        reason: 不可用时的原因描述，可用时为 ``None``。
    """

    available: bool
    reason: str | None = None
