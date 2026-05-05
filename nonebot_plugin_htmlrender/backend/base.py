from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Generic, Protocol, TypeVar

if TYPE_CHECKING:
    from contextlib import AsyncExitStack

    from nonebot_plugin_htmlrender.consts import RenderBackend

R = TypeVar("R")  # runtime handle type (backend-scoped)
S = TypeVar("S")  # session handle type (task-scoped)


@dataclass(slots=True)
class RenderRuntime(Generic[R]):
    backend: RenderBackend
    handle: R
    _aclose: Callable[[], Awaitable[None]]

    def attach(self, stack: AsyncExitStack) -> None:
        stack.push_async_callback(self.aclose)

    async def aclose(self) -> None:
        await self._aclose()

    async def __aenter__(self) -> RenderRuntime[R]:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()


@dataclass(slots=True)
class RenderSession(Generic[R, S]):
    runtime: RenderRuntime[R]
    handle: S
    _aclose: Callable[[], Awaitable[None]]

    def attach(self, stack: AsyncExitStack) -> None:
        stack.push_async_callback(self.aclose)

    async def aclose(self) -> None:
        await self._aclose()

    async def __aenter__(self) -> RenderSession[R, S]:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()


class Renderer(Protocol[R, S]):
    backend: RenderBackend

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        """Ordered async steps to prepare backend before open_runtime()."""
        return ()

    async def open_runtime(self) -> RenderRuntime[R]:
        """Create backend-scoped resources.

        Caller may attach the returned runtime to an AsyncExitStack, or close manually.
        """
        ...

    async def open_session(self, runtime: RenderRuntime[R], **kwargs: object) -> RenderSession[R, S]:
        """Create task-scoped resources bound to the given runtime.

        Caller may attach the returned session to an AsyncExitStack, or close manually.
        """
        ...

    def is_alive(self, session: RenderSession[R, S]) -> bool:
        ...
