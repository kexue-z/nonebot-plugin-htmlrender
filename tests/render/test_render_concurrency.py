import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from playwright.async_api import Page
import pytest

from nonebot_plugin_htmlrender._compat import get_browser, get_new_page
from nonebot_plugin_htmlrender.backend.base import (
    BackendCapability,
    RenderRuntime,
    RenderSession,
)
from nonebot_plugin_htmlrender.consts import RenderBackend
from nonebot_plugin_htmlrender.render import (
    Render,
    create_render,
    shutdown_render,
    startup_render,
)


@dataclass(slots=True)
class _SessionHandle:
    session_id: int


class _ConcurrencyBackend:
    backend = RenderBackend.PLAYWRIGHT
    capabilities = frozenset(
        {
            BackendCapability.RENDER_CONTEXT,
            BackendCapability.HTML_RENDER,
            BackendCapability.TEXT_RENDER,
            BackendCapability.MARKDOWN_RENDER,
            BackendCapability.TEMPLATE_RENDER,
            BackendCapability.TEMPLATE_HTML_RENDER,
            BackendCapability.HTML_ELEMENT_CAPTURE,
        }
    )

    def __init__(self) -> None:
        self.runtime_create_calls = 0
        self.runtime_close_calls = 0
        self.session_create_calls = 0
        self.session_close_calls = 0
        self.context_open_calls = 0
        self.render_html_calls = 0
        self._context_counter = 0
        self._session_counter = 0
        self.render_html_session_ids: list[int] = []
        self._alive_sessions: set[int] = set()

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        return ()

    async def create_runtime(self) -> RenderRuntime:
        self.runtime_create_calls += 1
        await asyncio.sleep(0.01)

        async def _close_runtime() -> None:
            self.runtime_close_calls += 1

        return RenderRuntime(
            backend=self.backend,
            handle=object(),
            _aclose=_close_runtime,
        )

    async def create_session(
        self,
        runtime: RenderRuntime,
        **kwargs: object,  # noqa: ARG002
    ) -> RenderSession:
        self.session_create_calls += 1
        self._session_counter += 1
        handle = _SessionHandle(session_id=self._session_counter)
        self._alive_sessions.add(handle.session_id)

        async def _close_session() -> None:
            self.session_close_calls += 1
            self._alive_sessions.discard(handle.session_id)

        return RenderSession(
            runtime=runtime,
            handle=handle,
            _aclose=_close_session,
        )

    def is_alive(self, session: RenderSession) -> bool:
        session_handle = session.handle
        if not isinstance(session_handle, _SessionHandle):
            return False
        return session_handle.session_id in self._alive_sessions

    @asynccontextmanager
    async def get_render_context(
        self,
        session: RenderSession,  # noqa: ARG002
        **kwargs: object,  # noqa: ARG002
    ):
        self.context_open_calls += 1
        self._context_counter += 1
        yield f"context-{self._context_counter}"

    async def render_html(
        self,
        session: RenderSession,
        request: object | str,
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        session_handle = session.handle
        if not isinstance(session_handle, _SessionHandle):
            raise RuntimeError("unexpected session handle type")
        self.render_html_calls += 1
        self.render_html_session_ids.append(session_handle.session_id)
        await asyncio.sleep(0.01)
        return f"ok:{request}".encode()

    async def render_text(
        self,
        session: RenderSession,
        text: str,
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        return await self.render_html(session, text)

    async def render_markdown(
        self,
        session: RenderSession,
        markdown_text: str = "",
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        return await self.render_html(session, markdown_text)

    async def render_template(
        self,
        session: RenderSession,
        request: object | str,
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        return await self.render_html(session, request)

    async def render_template_html(
        self,
        template: object | str,  # noqa: ARG002
        **kwargs: object,  # noqa: ARG002
    ) -> str:
        return "<html></html>"

    async def capture_html_element(
        self,
        session: RenderSession,
        url: str,
        element: str,
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        return await self.render_html(session, f"{url}#{element}")


@pytest.fixture
def concurrency_render() -> tuple[Render, _ConcurrencyBackend]:
    backend = _ConcurrencyBackend()
    return create_render(backend=backend), backend


@pytest.mark.anyio
async def test_render_layer_concurrency_behaviors(
    concurrency_render: tuple[Render, _ConcurrencyBackend],
) -> None:
    render, backend = concurrency_render

    sessions = await asyncio.gather(*[render.get_render() for _ in range(20)])
    assert len({id(session) for session in sessions}) == 1
    assert backend.runtime_create_calls == 1
    assert backend.session_create_calls == 1

    result = await asyncio.gather(
        *[render.render_html(f"<p>{index}</p>") for index in range(12)]
    )
    session = await render.get_render()
    assert all(item.startswith(b"ok:") for item in result)
    assert backend.render_html_calls == 12
    session_handle = session.handle
    assert isinstance(session_handle, _SessionHandle)
    assert set(backend.render_html_session_ids) == {session_handle.session_id}

    async def _use_context() -> object:
        async with render.get_render_context() as context:
            await asyncio.sleep(0.01)
            return context

    contexts = await asyncio.gather(*[_use_context() for _ in range(10)])
    assert len(set(contexts)) == 10
    assert backend.context_open_calls == 10

    await render.shutdown_render()
    await render.shutdown_render()

    assert render._runtime is None
    assert render._session is None
    assert backend.runtime_close_calls == 1
    assert backend.session_close_calls == 1


@pytest.mark.anyio
@pytest.mark.requires_browser
async def test_concurrent_pages_reuse_single_browser_and_close_lifecycle() -> None:
    await startup_render()
    browser = await get_browser()
    assert browser.is_connected()
    initial_context_count = len(browser.contexts)
    created_pages: list[Page] = []

    async def _worker(index: int, *, fail: bool = False) -> str:
        async with get_new_page() as raw_page:
            assert isinstance(raw_page, Page)
            page = raw_page
            created_pages.append(page)
            await page.set_content(f"<title>page-{index}</title><main>{index}</main>")
            await page.wait_for_timeout(10)
            title = await page.title()
            if fail:
                raise RuntimeError(f"expected-failure-{index}")
            return title

    try:
        ok_results = await asyncio.gather(*[_worker(index) for index in range(8)])
        mixed_results = await asyncio.gather(
            *[_worker(index, fail=index % 2 == 0) for index in range(6)],
            return_exceptions=True,
        )

        browser_after = await get_browser()
        assert browser_after is browser
        assert all(result.startswith("page-") for result in ok_results)
        assert any(isinstance(item, RuntimeError) for item in mixed_results)
        assert all(page.is_closed() for page in created_pages)

        for _ in range(40):
            if len(browser.contexts) == initial_context_count:
                break
            await asyncio.sleep(0.02)
        assert len(browser.contexts) == initial_context_count
    finally:
        await shutdown_render()
