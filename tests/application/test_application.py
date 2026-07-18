from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import anyio
import anyio.lowlevel
from exceptiongroup import ExceptionGroup
import pytest

from nonebot_plugin_htmlrender.application import (
    Application,
    Renderer,
    RendererBindings,
    RenderTemplateHtml,
)
from nonebot_plugin_htmlrender.rendering import (
    CapabilityCatalog,
    CapabilityKey,
    OperationAdmissionGate,
    ProviderLifecycleError,
    RenderTemplateHtmlRequest,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nonebot_plugin_htmlrender.preparation.service import HtmlPreparer
    from nonebot_plugin_htmlrender.resources.service import ResourceService
    from nonebot_plugin_htmlrender.resources.templating import (
        ExtensionSpec,
        FilterCallable,
    )


_PREPARATION = cast("HtmlPreparer", object())
_RESOURCES = cast("ResourceService", object())


@dataclass
class _FakeLifecycle:
    startup_calls: int = 0
    probe_calls: int = 0
    aclose_calls: int = 0
    startup_failures: list[Exception] = field(default_factory=list)
    aclose_failures: list[Exception] = field(default_factory=list)

    async def startup(self) -> None:
        self.startup_calls += 1
        await anyio.lowlevel.checkpoint()
        if self.startup_failures:
            raise self.startup_failures.pop(0)

    async def probe(self) -> None:
        self.probe_calls += 1

    async def aclose(self) -> None:
        self.aclose_calls += 1
        if self.aclose_failures:
            raise self.aclose_failures.pop(0)


@dataclass
class _FakeTemplatePreparer:
    calls: int = 0
    started: anyio.Event | None = None
    release: anyio.Event | None = None

    async def render_template_html(
        self,
        template_path: str | Path,
        template_name: str,
        variables: Mapping[str, object],
        *,
        filters: Mapping[str, FilterCallable] | None = None,
        extensions: Sequence[ExtensionSpec] = (),
    ) -> str:
        del template_path, template_name, variables, filters, extensions
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        return "<p>rendered</p>"


@dataclass
class _FakeResources:
    read_calls: int = 0
    authorize_calls: int = 0
    should_resolve_calls: int = 0
    started: anyio.Event | None = None
    release: anyio.Event | None = None

    def authorize_local(self, path: Path) -> Path:
        self.authorize_calls += 1
        return path

    def should_resolve(self, resolver: object | None = None) -> bool:
        del resolver
        self.should_resolve_calls += 1
        return True

    async def read_bytes(self, reference: object, *, refresh: bool = False) -> bytes:
        del reference, refresh
        self.read_calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        return b"content"


def _application(lifecycle: _FakeLifecycle) -> Application:
    admission = OperationAdmissionGate()
    return Application(
        renderer=Renderer(
            RendererBindings(),
            operation_admission=admission,
        ),
        preparation=_PREPARATION,
        resources=_RESOURCES,
        lifecycle=lifecycle,
        operation_admission=admission,
    )


def _template_application(
    lifecycle: _FakeLifecycle,
    preparer: _FakeTemplatePreparer,
) -> Application:
    typed_preparer = cast("HtmlPreparer", preparer)
    admission = OperationAdmissionGate()
    renderer = Renderer(
        RendererBindings(
            render_template_html=RenderTemplateHtml(preparer=typed_preparer)
        ),
        operation_admission=admission,
    )
    return Application(
        renderer=renderer,
        preparation=typed_preparer,
        resources=_RESOURCES,
        lifecycle=lifecycle,
        operation_admission=admission,
    )


def _template_request() -> RenderTemplateHtmlRequest:
    return RenderTemplateHtmlRequest(
        template_path="templates",
        template_name="page.html",
        variables={"title": "hello"},
    )


def _resource_application(
    lifecycle: _FakeLifecycle,
    resources: _FakeResources,
) -> Application:
    admission = OperationAdmissionGate()
    return Application(
        renderer=Renderer(
            RendererBindings(),
            operation_admission=admission,
        ),
        preparation=_PREPARATION,
        resources=cast("ResourceService", resources),
        lifecycle=lifecycle,
        operation_admission=admission,
    )


async def test_startup_is_idempotent() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    await app.startup()
    await app.startup()

    assert lifecycle.startup_calls == 1


async def test_concurrent_startup_invokes_lifecycle_once() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(app.startup)
        task_group.start_soon(app.startup)
        task_group.start_soon(app.startup)

    assert lifecycle.startup_calls == 1


async def test_startup_failure_allows_retry() -> None:
    lifecycle = _FakeLifecycle(startup_failures=[RuntimeError("boom")])
    app = _application(lifecycle)

    with pytest.raises(ProviderLifecycleError, match="boom") as captured:
        await app.startup()
    assert isinstance(captured.value.__cause__, RuntimeError)
    await app.startup()

    assert lifecycle.startup_calls == 2


async def test_aclose_is_idempotent_and_blocks_restart() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    await app.startup()
    await app.aclose()
    await app.aclose()

    assert lifecycle.aclose_calls == 1
    with pytest.raises(ProviderLifecycleError, match="closed"):
        await app.startup()


async def test_aclose_without_startup_still_closes_lifecycle() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    await app.aclose()

    assert lifecycle.aclose_calls == 1


async def test_failed_close_can_be_retried_but_cannot_restart() -> None:
    lifecycle = _FakeLifecycle(aclose_failures=[RuntimeError("cache busy")])
    app = _application(lifecycle)
    await app.startup()

    with pytest.raises(ProviderLifecycleError, match="cache busy") as captured:
        await app.aclose()
    assert isinstance(captured.value.__cause__, RuntimeError)
    with pytest.raises(ProviderLifecycleError, match="closing"):
        await app.startup()

    await app.aclose()
    await app.aclose()

    assert lifecycle.aclose_calls == 2


async def test_failed_close_permanently_rejects_renderer_operations() -> None:
    lifecycle = _FakeLifecycle(aclose_failures=[RuntimeError("cache busy")])
    preparer = _FakeTemplatePreparer()
    app = _template_application(lifecycle, preparer)
    renderer = app.renderer

    with pytest.raises(ProviderLifecycleError, match="cache busy"):
        await app.aclose()
    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        await renderer.render_template_html(_template_request())

    assert preparer.calls == 0
    await app.aclose()


async def test_close_drains_complete_use_case_and_rejects_new_operations() -> None:
    lifecycle = _FakeLifecycle()
    preparer = _FakeTemplatePreparer(started=anyio.Event(), release=anyio.Event())
    app = _template_application(lifecycle, preparer)
    renderer = app.renderer
    rendered: list[str] = []
    close_finished = anyio.Event()

    async def render() -> None:
        rendered.append(str(await renderer.render_template_html(_template_request())))

    async def close() -> None:
        await app.aclose()
        close_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(render)
        assert preparer.started is not None
        await preparer.started.wait()
        task_group.start_soon(close)
        await anyio.lowlevel.checkpoint()

        assert lifecycle.aclose_calls == 0
        assert preparer.release is not None
        preparer.release.set()
        await close_finished.wait()

    assert rendered == ["<p>rendered</p>"]
    assert preparer.calls == 1
    assert lifecycle.aclose_calls == 1


async def test_close_drains_public_preparation_facade() -> None:
    lifecycle = _FakeLifecycle()
    preparer = _FakeTemplatePreparer(started=anyio.Event(), release=anyio.Event())
    app = _template_application(lifecycle, preparer)
    preparation = app.preparation
    close_finished = anyio.Event()

    async def prepare() -> None:
        await preparation.render_template_html(
            "templates",
            "page.html",
            {"title": "hello"},
        )

    async def close() -> None:
        await app.aclose()
        close_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(prepare)
        assert preparer.started is not None
        await preparer.started.wait()
        task_group.start_soon(close)
        await anyio.lowlevel.checkpoint()

        assert lifecycle.aclose_calls == 0
        assert not close_finished.is_set()
        assert preparer.release is not None
        preparer.release.set()
        await close_finished.wait()

    assert lifecycle.aclose_calls == 1


async def test_close_rejects_renderer_retained_before_shutdown() -> None:
    lifecycle = _FakeLifecycle()
    preparer = _FakeTemplatePreparer()
    app = _template_application(lifecycle, preparer)
    renderer = app.renderer

    await app.aclose()

    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        await renderer.render_template_html(_template_request())
    assert preparer.calls == 0


async def test_close_rejects_preparer_retained_before_shutdown() -> None:
    lifecycle = _FakeLifecycle()
    preparer = _FakeTemplatePreparer()
    app = _template_application(lifecycle, preparer)
    preparation = app.preparation

    await app.aclose()

    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        await preparation.render_template_html(
            "templates",
            "page.html",
            {"title": "hello"},
        )
    assert preparer.calls == 0


async def test_close_rejects_resources_retained_before_shutdown() -> None:
    lifecycle = _FakeLifecycle()
    resources = _FakeResources()
    app = _resource_application(lifecycle, resources)
    public_resources = app.resources

    await app.aclose()

    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        await public_resources.read_bytes("asset.png")
    assert resources.read_calls == 0


async def test_close_drains_public_resource_facade() -> None:
    lifecycle = _FakeLifecycle()
    resources = _FakeResources(started=anyio.Event(), release=anyio.Event())
    app = _resource_application(lifecycle, resources)
    public_resources = app.resources
    close_finished = anyio.Event()

    async def read() -> None:
        await public_resources.read_bytes("asset.png")

    async def close() -> None:
        await app.aclose()
        close_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(read)
        assert resources.started is not None
        await resources.started.wait()
        task_group.start_soon(close)
        await anyio.lowlevel.checkpoint()

        assert lifecycle.aclose_calls == 0
        assert not close_finished.is_set()
        assert resources.release is not None
        resources.release.set()
        await close_finished.wait()

    assert lifecycle.aclose_calls == 1


async def test_lifecycle_exception_group_is_exposed_as_stable_error() -> None:
    failure = ExceptionGroup(
        "cleanup failed",
        [RuntimeError("engine close failed"), RuntimeError("cache clear failed")],
    )
    app = _application(_FakeLifecycle(aclose_failures=[failure]))

    with pytest.raises(ProviderLifecycleError, match="cleanup failed") as captured:
        await app.aclose()

    assert captured.value.__cause__ is failure


async def test_probe_delegates_to_lifecycle() -> None:
    lifecycle = _FakeLifecycle()
    app = _application(lifecycle)

    await app.probe()

    assert lifecycle.startup_calls == 1
    assert lifecycle.probe_calls == 1

    await app.aclose()
    with pytest.raises(ProviderLifecycleError, match="closed"):
        await app.probe()


def test_capability_catalog_defaults_to_empty() -> None:
    app = _application(_FakeLifecycle())

    class _Marker:
        pass

    assert app.extensions.names() == frozenset()
    assert app.extensions.get(CapabilityKey("test.marker", _Marker)) is None


def test_capability_catalog_passthrough() -> None:
    class _Marker:
        pass

    marker = _Marker()
    key = CapabilityKey("test.marker", _Marker)
    catalog = CapabilityCatalog().with_capability(key, marker)
    admission = OperationAdmissionGate()
    app = Application(
        renderer=Renderer(
            RendererBindings(),
            operation_admission=admission,
        ),
        preparation=_PREPARATION,
        resources=_RESOURCES,
        lifecycle=_FakeLifecycle(),
        operation_admission=admission,
        extensions=catalog,
    )

    assert app.extensions.require(key) is marker


def test_application_exposes_composition_owned_services() -> None:
    app = _application(_FakeLifecycle())

    assert app.preparation is app.preparation
    assert app.resources is app.resources
    assert app.preparation is not _PREPARATION
    assert app.resources is not _RESOURCES


def test_renderer_does_not_expose_lifecycle_controller() -> None:
    renderer = Renderer(
        RendererBindings(),
        operation_admission=OperationAdmissionGate(),
    )

    assert not hasattr(renderer, "operation_admission")


async def test_close_rejects_synchronous_resource_facade_operations() -> None:
    resources = _FakeResources()
    app = _resource_application(_FakeLifecycle(), resources)
    public_resources = app.resources

    await app.aclose()

    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        public_resources.authorize_local(Path("asset.png"))
    with pytest.raises(ProviderLifecycleError, match="closing or closed"):
        public_resources.should_resolve()

    assert resources.authorize_calls == 0
    assert resources.should_resolve_calls == 0
