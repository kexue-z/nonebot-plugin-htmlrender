from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from nonebot_plugin_htmlrender import render
from nonebot_plugin_htmlrender.backend.base import (
    BackendCapability,
    RenderRuntime,
    RenderSession,
)
from nonebot_plugin_htmlrender.consts import RenderBackend
from nonebot_plugin_htmlrender.preparation import (
    PreparedHtml,
    RasterOptions,
    prepare_html,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


class _SimpleBackend:
    backend = RenderBackend.PLAYWRIGHT
    capabilities = frozenset(
        {
            BackendCapability.RENDER_CONTEXT,
            BackendCapability.HTML_RENDER,
            BackendCapability.HTML_RASTERIZE,
            BackendCapability.TEXT_RENDER,
            BackendCapability.MARKDOWN_RENDER,
            BackendCapability.TEMPLATE_RENDER,
            BackendCapability.TEMPLATE_HTML_RENDER,
            BackendCapability.HTML_ELEMENT_CAPTURE,
        }
    )

    def startup_steps(self) -> tuple[Any, ...]:
        return ()

    async def create_runtime(self) -> RenderRuntime:
        async def _close() -> None:
            return None

        return RenderRuntime(
            backend=self.backend,
            handle=object(),
            _aclose=_close,
        )

    async def create_session(
        self,
        runtime: RenderRuntime,
        **kwargs: object,  # noqa: ARG002
    ) -> RenderSession:
        async def _close() -> None:
            return None

        return RenderSession(
            runtime=runtime,
            handle=object(),
            _aclose=_close,
        )

    def is_alive(self, session: RenderSession) -> bool:  # noqa: ARG002
        return True

    @asynccontextmanager
    async def get_render_context(
        self,
        session: RenderSession,  # noqa: ARG002
        **kwargs: object,  # noqa: ARG002
    ):
        yield "ctx"

    async def render_html(
        self,
        session: RenderSession,  # noqa: ARG002
        request: object,
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        return str(request).encode()

    async def rasterize_html(
        self,
        session: RenderSession,  # noqa: ARG002
        prepared: PreparedHtml,
        options: RasterOptions,
    ) -> bytes:
        return f"{options.width}:{prepared.markup}".encode()

    async def render_text(
        self,
        session: RenderSession,  # noqa: ARG002
        text: str,
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        return text.encode()

    async def render_markdown(
        self,
        session: RenderSession,  # noqa: ARG002
        markdown_text: str = "",
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        return markdown_text.encode()

    async def render_template(
        self,
        session: RenderSession,  # noqa: ARG002
        request: object,
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        return str(request).encode()

    async def render_template_html(
        self,
        template: object,
        **kwargs: object,  # noqa: ARG002
    ) -> str:
        return str(template)

    async def capture_html_element(
        self,
        session: RenderSession,  # noqa: ARG002
        url: str,
        element: str,
        **kwargs: object,  # noqa: ARG002
    ) -> bytes:
        return f"{url}#{element}".encode()


class _HtmlOnlyBackend(_SimpleBackend):
    capabilities = frozenset({BackendCapability.HTML_RENDER})


class _RasterOnlyBackend(_SimpleBackend):
    capabilities = frozenset({BackendCapability.HTML_RASTERIZE})


def test_render_backend_status_wrapper_functions(mocker: MockerFixture) -> None:
    status_item = SimpleNamespace(backend=RenderBackend.SKIA, available=False)
    mocker.patch.object(
        render, "backend_available_backends", return_value=(RenderBackend.PLAYWRIGHT,)
    )
    mocker.patch.object(
        render, "backend_registered_backends", return_value=(RenderBackend.PLAYWRIGHT,)
    )
    mocker.patch.object(render, "backend_status_items", return_value=(status_item,))
    mocker.patch.object(render, "backend_get_status", return_value=status_item)
    mocker.patch.object(render, "backend_is_available", return_value=False)
    mocker.patch.object(render, "backend_is_registered", return_value=True)

    assert render.available_render_backends() == (RenderBackend.PLAYWRIGHT,)
    assert render.unavailable_render_backends() == (RenderBackend.SKIA,)
    assert render.registered_render_backends() == (RenderBackend.PLAYWRIGHT,)
    assert render.get_render_backend_status(RenderBackend.SKIA) is status_item
    assert render.list_render_backend_statuses() == (status_item,)
    assert render.is_render_backend_available(RenderBackend.SKIA) is False
    assert render.is_render_backend_registered(RenderBackend.SKIA) is True


def test_get_default_render_caches_instance(mocker: MockerFixture) -> None:
    render._state.default_render = None
    created = render.create_render(backend=_SimpleBackend())
    mocker.patch.object(render, "create_render", return_value=created)

    first = render.get_default_render()
    second = render.get_default_render()

    assert first is second
    assert first is created


@pytest.mark.anyio
async def test_render_default_proxy_delegates_methods(mocker: MockerFixture) -> None:
    backend = _SimpleBackend()
    instance = render.create_render(backend=backend)
    mocker.patch.object(render, "get_default_render", return_value=instance)

    assert await render.render_html("<p/>") == b"<p/>"
    assert await render.render_text("x") == b"x"
    assert await render.render_markdown("## x") == b"## x"
    assert await render.render_template("tpl") == b"tpl"
    assert await render.render_template_html("tpl") == "tpl"
    assert await render.capture_html_element("https://e", "#x") == b"https://e##x"


@pytest.mark.anyio
async def test_html_render_and_rasterize_use_distinct_capabilities() -> None:
    prepared = prepare_html("<main>ok</main>")
    options = RasterOptions(width=320)

    html_render = render.create_render(backend=_HtmlOnlyBackend())
    assert await html_render.render_html("<p>html</p>") == b"<p>html</p>"
    with pytest.raises(RuntimeError, match="html_rasterize"):
        await html_render.rasterize_html(prepared, options)
    await html_render.shutdown_render()

    raster_render = render.create_render(backend=_RasterOnlyBackend())
    assert (
        await raster_render.rasterize_html(prepared, options) == b"320:<main>ok</main>"
    )
    with pytest.raises(RuntimeError, match="html_render"):
        await raster_render.render_html("<p>html</p>")
    await raster_render.shutdown_render()


@pytest.mark.anyio
async def test_render_context_and_session_lifecycle() -> None:
    instance = render.create_render(backend=_SimpleBackend())
    async with instance.get_render_context() as context:
        assert context == "ctx"

    session = await instance.get_render()
    assert session is not None
    await instance.shutdown_render()


@pytest.mark.anyio
async def test_global_shutdown_render_clears_state(mocker: MockerFixture) -> None:
    fake = mocker.Mock()
    fake.shutdown_render = mocker.AsyncMock()
    render._state.default_render = fake

    await render.shutdown_render()
    assert render._state.default_render is None
    fake.shutdown_render.assert_awaited_once_with()

    # no-op when already empty
    await render.shutdown_render()


def test_process_rss_helpers(mocker: MockerFixture) -> None:
    usage = SimpleNamespace(ru_maxrss=2048)
    mocker.patch.object(render, "_resource_getrusage", return_value=usage)
    mocker.patch.object(render, "_resource_rusage_self", 1)
    mocker.patch(
        "nonebot_plugin_htmlrender.render.os.uname",
        return_value=SimpleNamespace(sysname="Linux"),
    )
    assert render._get_process_rss_mb() == 2.0

    mocker.patch(
        "nonebot_plugin_htmlrender.render.os.uname",
        return_value=SimpleNamespace(sysname="Darwin"),
    )
    assert render._get_process_rss_mb() == pytest.approx(2048 / (1024 * 1024))

    mocker.patch.object(render, "_resource_getrusage", None)
    assert render._get_process_rss_mb() is None


def test_require_browser_target_raises_for_non_browser() -> None:
    from nonebot_plugin_htmlrender._compat import _require_browser  # noqa: PLC0415

    session = SimpleNamespace(handle=object())
    with pytest.raises(RuntimeError, match="not a Browser instance"):
        _require_browser(session)


@pytest.mark.anyio
async def test_top_level_browser_wrappers(mocker: MockerFixture) -> None:
    from nonebot_plugin_htmlrender import _compat  # noqa: PLC0415

    session = SimpleNamespace(handle=object())
    mocker.patch.object(
        _compat, "get_render", new=mocker.AsyncMock(return_value=session)
    )
    browser_obj = SimpleNamespace(name="browser")
    mocker.patch.object(_compat, "_require_browser", return_value=browser_obj)
    mocker.patch.object(
        _compat, "startup_render", new=mocker.AsyncMock(return_value=session)
    )
    mocker.patch.object(_compat, "shutdown_render", new=mocker.AsyncMock())

    assert await _compat.get_browser() is browser_obj
    assert await _compat.startup_htmlrender() is browser_obj
    await _compat.shutdown_htmlrender()
    await _compat._launch("chromium")
