from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
import threading
from typing import TYPE_CHECKING, Any, TypeVar, cast

import anyio
from anyio.to_thread import run_sync

from nonebot_plugin_htmlrender.resources import read_resource_bytes

from .errors import TakumiRuntimeError
from .types import NativeCompiledHtml, NativeRenderer, TakumiImageResource

if TYPE_CHECKING:
    from .config import TakumiConfig, TakumiFontConfig

T = TypeVar("T")


@dataclass(slots=True)
class _CompiledCache:
    max_entries: int
    html: OrderedDict[tuple[object, ...], object] = field(default_factory=OrderedDict)
    stylesheets: OrderedDict[str, object] = field(default_factory=OrderedDict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    @staticmethod
    def _get_or_insert(
        cache: OrderedDict[Any, object],
        key: Any,
        factory: Callable[[], object],
        max_entries: int,
    ) -> object:
        cached = cache.get(key)
        if cached is not None:
            cache.move_to_end(key)
            return cached

        value = factory()
        if max_entries > 0:
            cache[key] = value
            while len(cache) > max_entries:
                cache.popitem(last=False)
        return value

    def get_html(
        self,
        renderer: NativeRenderer,
        markup: str,
        html_options: object,
        options_key: tuple[object, ...],
    ) -> NativeCompiledHtml:
        with self.lock:
            return cast(
                "NativeCompiledHtml",
                self._get_or_insert(
                    self.html,
                    (markup, *options_key),
                    lambda: renderer.compile_html(markup, html_options=html_options),
                    self.max_entries,
                ),
            )

    def get_stylesheet(self, renderer: NativeRenderer, css: str) -> object:
        with self.lock:
            return self._get_or_insert(
                self.stylesheets,
                css,
                lambda: renderer.compile_stylesheet_lossy(css),
                self.max_entries,
            )

    def clear(self) -> None:
        with self.lock:
            self.html.clear()
            self.stylesheets.clear()


@dataclass(slots=True)
class TakumiRuntimeState:
    renderer: NativeRenderer
    limiter: anyio.CapacityLimiter
    config: TakumiConfig
    registered_font_families: tuple[str, ...] = ()
    closed: bool = False
    _compiled: _CompiledCache = field(init=False)

    def __post_init__(self) -> None:
        self._compiled = _CompiledCache(self.config.compiled_cache_max_entries)

    def _ensure_open(self) -> None:
        if self.closed:
            raise TakumiRuntimeError("Takumi runtime is closed.")

    def add_registered_font_families(self, families: Sequence[str]) -> None:
        with self._compiled.lock:
            self.registered_font_families = tuple(
                dict.fromkeys((*self.registered_font_families, *families))
            )

    async def run(
        self, func: Callable[..., T], /, *args: object, **kwargs: object
    ) -> T:
        self._ensure_open()
        return await run_sync(
            partial(func, *args, **kwargs),
            limiter=self.limiter,
        )

    async def call_renderer(
        self, method_name: str, /, *args: object, **kwargs: object
    ) -> object:
        def _invoke() -> object:
            method = getattr(self.renderer, method_name)
            return method(*args, **_normalize_call_kwargs(kwargs))

        return await self.run(_invoke)

    async def call_document(
        self,
        method_name: str,
        markup: str,
        stylesheets: Sequence[str],
        /,
        **kwargs: object,
    ) -> object:
        """Compile/cache a document, then execute one compiled native operation."""

        def _invoke() -> object:
            from takumi_py import HtmlOptions  # noqa: PLC0415

            options = self.config.html_options
            html_options = HtmlOptions(
                presets=options.presets,
                tailwind_property=options.tailwind_property,
                max_depth=options.max_depth,
            )
            options_key = (
                options.presets,
                options.tailwind_property,
                options.max_depth,
            )
            compiled_html = self._compiled.get_html(
                self.renderer,
                markup,
                html_options,
                options_key,
            )
            node = compiled_html.node
            compiled_stylesheets = tuple(
                self._compiled.get_stylesheet(self.renderer, css) for css in stylesheets
            )
            method = getattr(self.renderer, method_name)
            return method(
                node,
                stylesheets=compiled_stylesheets,
                **_normalize_call_kwargs(kwargs),
            )

        return await self.run(_invoke)

    async def compile_document(
        self,
        markup: str,
        stylesheets: Sequence[str],
    ) -> tuple[object, tuple[object, ...]]:
        """Return the same cached HTML/CSS objects used by document execution."""

        def _compile() -> tuple[object, tuple[object, ...]]:
            from takumi_py import HtmlOptions  # noqa: PLC0415

            options = self.config.html_options
            html_options = HtmlOptions(
                presets=options.presets,
                tailwind_property=options.tailwind_property,
                max_depth=options.max_depth,
            )
            options_key = (
                options.presets,
                options.tailwind_property,
                options.max_depth,
            )
            compiled_html = self._compiled.get_html(
                self.renderer,
                markup,
                html_options,
                options_key,
            )
            compiled_stylesheets = tuple(
                self._compiled.get_stylesheet(self.renderer, css) for css in stylesheets
            )
            return compiled_html.node, compiled_stylesheets

        return await self.run(_compile)

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._compiled.clear()


async def _load_font_payloads(
    fonts: Sequence[TakumiFontConfig],
    *,
    config: TakumiConfig,
) -> tuple[bytes, ...]:
    payloads: list[bytes | None] = [None] * len(fonts)

    async def _read_one(index: int, font: TakumiFontConfig) -> None:
        payloads[index] = await read_resource_bytes(
            font.path,
            policy=config.font_cache_policy,
        )

    async with anyio.create_task_group() as task_group:
        for index, font in enumerate(fonts):
            task_group.start_soon(_read_one, index, font)

    if any(payload is None for payload in payloads):
        raise TakumiRuntimeError("One or more configured fonts could not be loaded.")
    return cast("tuple[bytes, ...]", tuple(payloads))


def _normalize_images(images: Sequence[object] | None) -> list[object] | None:
    if images is None:
        return None

    from takumi_py import ImageResource  # noqa: PLC0415

    normalized: list[object] = []
    for image in images:
        if isinstance(image, TakumiImageResource):
            normalized.append(ImageResource(image.src, image.data, cache=image.cache))
        else:
            normalized.append(image)
    return normalized


def _normalize_call_kwargs(kwargs: dict[str, object]) -> dict[str, object]:
    """Convert adapter image values inside the worker that executes native code."""
    normalized = dict(kwargs)
    for name in ("images", "fetched_resources"):
        value = normalized.get(name)
        if value is not None:
            if not isinstance(value, Sequence):
                raise TypeError(f"{name} must be a sequence of image resources.")
            normalized[name] = _normalize_images(value)
    return normalized


def render_defaults(
    state: TakumiRuntimeState,
    *,
    images: Sequence[object] | None = None,
) -> dict[str, object]:
    """Build common native options without hiding explicit caller overrides."""
    options: dict[str, object] = {}
    if images is not None:
        options["images"] = tuple(images)
    if state.config.font_families:
        options["font_families"] = tuple(state.config.font_families)
    if state.config.default_lang is not None:
        options["lang"] = state.config.default_lang
    return options


async def create_runtime_state(config: TakumiConfig) -> TakumiRuntimeState:
    """Create one renderer and register cached font bytes exactly once."""
    limiter = anyio.CapacityLimiter(config.max_concurrency)
    fonts = tuple(config.fonts)
    payloads = await _load_font_payloads(fonts, config=config) if fonts else ()

    def _build() -> tuple[NativeRenderer, tuple[str, ...]]:
        from takumi_py import FontResource, Renderer  # noqa: PLC0415

        renderer = Renderer(load_default_fonts=config.load_default_fonts)
        resources = [
            FontResource(
                payload,
                name=font.name,
                weight=font.weight,
                style=font.style,
                subset_of=font.subset_of,
                generic_family=font.generic_family,
            )
            for font, payload in zip(fonts, payloads, strict=True)
        ]
        families = renderer.register_fonts(resources) if resources else ()
        return cast("NativeRenderer", renderer), tuple(dict.fromkeys(families))

    renderer, registered_families = await run_sync(
        _build,
        limiter=limiter,
    )
    return TakumiRuntimeState(
        renderer=renderer,
        limiter=limiter,
        config=config.model_copy(deep=True),
        registered_font_families=registered_families,
    )


def require_runtime_state(handle: object) -> TakumiRuntimeState:
    if not isinstance(handle, TakumiRuntimeState):
        raise TakumiRuntimeError(
            f"Expected TakumiRuntimeState, got {type(handle).__name__}."
        )
    handle._ensure_open()
    return handle


__all__ = [
    "TakumiRuntimeState",
    "create_runtime_state",
    "render_defaults",
    "require_runtime_state",
]
