from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from hashlib import sha256
import math
from pathlib import Path
import threading
from typing import TYPE_CHECKING, TypeVar, cast

import anyio
from anyio.to_thread import run_sync

from nonebot_plugin_htmlrender.resources import FileCachePolicy, read_resource_bytes
from nonebot_plugin_htmlrender.resources.weighted_cache import (
    SyncWeightedSingleflightLRU,
    WeightedCacheStats,
)

from .errors import TakumiInputError, TakumiRuntimeError
from .source import normalize_image_input
from .validation import ensure_utf8, utf8_weight, validate_native_strings

if TYPE_CHECKING:
    from typing import Protocol

    from takumi_py import FontResourceInput

    from .config import GenericFontFamily, TakumiConfig, TakumiFontConfig
    from .types import NativeCompiledHtml, NativeRenderer, TakumiImageResource

    class _FontResourceLike(Protocol):
        data: bytes
        name: str | None
        weight: float | None
        style: str | None
        subset_of: str | None
        generic_family: str | None


T = TypeVar("T")

_GENERIC_FONT_FAMILIES = frozenset(
    {
        "serif",
        "sans-serif",
        "monospace",
        "cursive",
        "fantasy",
        "system-ui",
        "ui-serif",
        "ui-sans-serif",
        "ui-monospace",
        "ui-rounded",
        "emoji",
        "math",
        "fangsong",
    }
)


@dataclass(frozen=True, slots=True)
class _FontSpec:
    data: bytes
    name: str | None = None
    weight: float | None = None
    style: str | None = None
    subset_of: str | None = None
    generic_family: GenericFontFamily | None = None

    @property
    def digest(self) -> str:
        return sha256(self.data).hexdigest()

    @property
    def options(self) -> tuple[object, ...]:
        return (
            self.name,
            self.weight,
            self.style,
            self.subset_of,
            self.generic_family,
        )

    @property
    def generated_source(self) -> str:
        fingerprint = sha256()
        fingerprint.update(self.data)
        for value in self.options:
            fingerprint.update(b"\0")
            fingerprint.update(repr(value).encode("utf-8"))
        return f"memory:sha256:{fingerprint.hexdigest()}"

    def to_native(self) -> FontResourceInput:
        from takumi_py import FontResource  # noqa: PLC0415

        return FontResource(
            self.data,
            name=self.name,
            weight=self.weight,
            style=self.style,
            subset_of=self.subset_of,
            generic_family=self.generic_family,
        )


@dataclass(frozen=True, slots=True)
class _FontRegistration:
    digest: str
    options: tuple[object, ...]
    families: tuple[str, ...]


def _validate_font_spec(spec: _FontSpec, *, field_name: str) -> _FontSpec:
    for attribute, value in (
        ("name", spec.name),
        ("style", spec.style),
        ("subset_of", spec.subset_of),
        ("generic_family", spec.generic_family),
    ):
        if value is not None:
            ensure_utf8(value, field=f"{field_name}.{attribute}")
    if spec.weight is not None and (
        not math.isfinite(spec.weight) or not 1 <= spec.weight <= 1000
    ):
        raise TakumiInputError(
            f"{field_name}.weight",
            "must be finite and between 1 and 1000",
        )
    if (
        spec.generic_family is not None
        and spec.generic_family not in _GENERIC_FONT_FAMILIES
    ):
        raise TakumiInputError(
            f"{field_name}.generic_family",
            f"unsupported generic font family {spec.generic_family!r}",
        )
    return spec


def _coerce_font_spec(font: object, *, field_name: str) -> _FontSpec:
    if isinstance(font, bytes):
        return _FontSpec(data=font)
    try:
        resource = cast("_FontResourceLike", font)
        data = resource.data
        name = resource.name
        weight = resource.weight
        style = resource.style
        subset_of = resource.subset_of
        generic_family = cast("GenericFontFamily | None", resource.generic_family)
    except Exception as error:
        raise TypeError(
            f"{field_name} must be bytes or expose FontResource-compatible fields."
        ) from error
    if not isinstance(data, bytes):
        raise TypeError(f"{field_name}.data must be bytes, got {type(data).__name__}.")
    for attribute, value in (
        ("name", name),
        ("style", style),
        ("subset_of", subset_of),
        ("generic_family", generic_family),
    ):
        if value is not None and not isinstance(value, str):
            raise TypeError(
                f"{field_name}.{attribute} must be str or None, "
                f"got {type(value).__name__}."
            )
        if isinstance(value, str):
            ensure_utf8(value, field=f"{field_name}.{attribute}")
    if weight is not None:
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise TypeError(
                f"{field_name}.weight must be a number or None, "
                f"got {type(weight).__name__}."
            )
        weight = float(weight)
    return _validate_font_spec(
        _FontSpec(
            data=data,
            name=name,
            weight=weight,
            style=style,
            subset_of=subset_of,
            generic_family=generic_family,
        ),
        field_name=field_name,
    )


def _font_source(path: str | Path) -> str:
    return Path(path).expanduser().resolve().as_uri()


def _validate_font_registration(
    source: str,
    spec: _FontSpec,
    existing: _FontRegistration | None,
) -> None:
    if existing is None:
        return
    if existing.digest == spec.digest and existing.options == spec.options:
        return
    raise TakumiRuntimeError(
        f"Font source {source!r} changed after this Takumi runtime was built; "
        "create a new runtime before registering changed font bytes or options."
    )


@dataclass(slots=True)
class TakumiRuntimeState:
    renderer: NativeRenderer | None
    limiter: anyio.CapacityLimiter
    config: TakumiConfig
    registered_font_families: tuple[str, ...] = ()
    _compiled: SyncWeightedSingleflightLRU[tuple[object, ...], object] = field(
        init=False,
        repr=False,
    )
    _lifecycle_lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )
    _font_lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )
    _drained: threading.Event = field(
        default_factory=threading.Event,
        init=False,
        repr=False,
    )
    _closed_event: threading.Event = field(
        default_factory=threading.Event,
        init=False,
        repr=False,
    )
    _lifecycle: str = field(default="open", init=False, repr=False)
    _active_calls: int = field(default=0, init=False, repr=False)
    _font_registrations: dict[str, _FontRegistration] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self._compiled = SyncWeightedSingleflightLRU(
            max_entries=self.config.compiled_cache_max_entries,
            max_weight=self.config.compiled_cache_max_bytes,
        )
        self._drained.set()

    @property
    def closed(self) -> bool:
        with self._lifecycle_lock:
            return self._lifecycle == "closed"

    @property
    def closing(self) -> bool:
        with self._lifecycle_lock:
            return self._lifecycle == "closing"

    @property
    def compiled_cache_stats(self) -> WeightedCacheStats:
        return self._compiled.stats()

    def _ensure_open(self) -> None:
        with self._lifecycle_lock:
            if self._lifecycle != "open":
                raise TakumiRuntimeError(
                    f"Takumi runtime is {self._lifecycle}; new calls are rejected."
                )

    def _begin_call(self) -> None:
        with self._lifecycle_lock:
            if self._lifecycle != "open":
                raise TakumiRuntimeError(
                    f"Takumi runtime is {self._lifecycle}; new calls are rejected."
                )
            self._active_calls += 1
            self._drained.clear()

    def _end_call(self) -> None:
        with self._lifecycle_lock:
            self._active_calls -= 1
            if self._active_calls == 0:
                self._drained.set()

    def _renderer_for_admitted_call(self) -> NativeRenderer:
        with self._lifecycle_lock:
            renderer = self.renderer
        if renderer is None:
            raise TakumiRuntimeError("Takumi renderer has already been released.")
        return renderer

    def add_registered_font_families(self, families: Sequence[str]) -> None:
        with self._font_lock:
            self.registered_font_families = tuple(
                dict.fromkeys((*self.registered_font_families, *families))
            )

    async def run(
        self, func: Callable[..., T], /, *args: object, **kwargs: object
    ) -> T:
        self._begin_call()
        try:
            return await run_sync(
                partial(func, *args, **kwargs),
                limiter=self.limiter,
            )
        finally:
            self._end_call()

    async def call_renderer(
        self, method_name: str, /, *args: object, **kwargs: object
    ) -> object:
        normalized_kwargs = _prepare_call_kwargs(method_name, kwargs)
        for index, value in enumerate(args):
            validate_native_strings(
                value,
                field=f"{method_name}.args[{index}]",
            )

        def _invoke() -> object:
            renderer = self._renderer_for_admitted_call()
            method = getattr(renderer, method_name)
            return method(*args, **_to_native_call_kwargs(normalized_kwargs))

        return await self.run(_invoke)

    def _compile_document(
        self,
        renderer: NativeRenderer,
        html: str,
        stylesheets: Sequence[str],
    ) -> tuple[object, tuple[object, ...]]:
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
        compiled_html = cast(
            "NativeCompiledHtml",
            self._compiled.get_or_insert(
                ("html", html, *options_key),
                weight=utf8_weight(
                    html,
                    options.presets,
                    options.tailwind_property or "",
                ),
                factory=lambda: renderer.compile_html(
                    html,
                    html_options=html_options,
                ),
            ),
        )
        compiled_stylesheets = tuple(
            self._compiled.get_or_insert(
                ("css-lossy", css),
                weight=utf8_weight(css),
                factory=lambda css=css: renderer.compile_stylesheet_lossy(css),
            )
            for css in stylesheets
        )
        return compiled_html.node, compiled_stylesheets

    async def call_document(
        self,
        method_name: str,
        html: str,
        stylesheets: Sequence[str],
        /,
        **kwargs: object,
    ) -> object:
        """Compile/cache a document, then execute one compiled native operation."""

        ensure_utf8(html, field="document.html")
        for index, css in enumerate(stylesheets):
            ensure_utf8(css, field=f"document.stylesheets[{index}]")
        normalized_kwargs = _prepare_call_kwargs(method_name, kwargs)

        def _invoke() -> object:
            renderer = self._renderer_for_admitted_call()
            node, compiled_stylesheets = self._compile_document(
                renderer,
                html,
                stylesheets,
            )
            method = getattr(renderer, method_name)
            return method(
                node,
                stylesheets=compiled_stylesheets,
                **_to_native_call_kwargs(normalized_kwargs),
            )

        return await self.run(_invoke)

    async def compile_document(
        self,
        html: str,
        stylesheets: Sequence[str],
    ) -> tuple[object, tuple[object, ...]]:
        """Return the same cached HTML/CSS objects used by document execution."""

        ensure_utf8(html, field="document.html")
        for index, css in enumerate(stylesheets):
            ensure_utf8(css, field=f"document.stylesheets[{index}]")

        def _compile() -> tuple[object, tuple[object, ...]]:
            return self._compile_document(
                self._renderer_for_admitted_call(),
                html,
                stylesheets,
            )

        return await self.run(_compile)

    async def compile_stylesheet(self, css: str, *, lossy: bool) -> object:
        """Compile one stylesheet through the runtime-local weighted cache."""

        ensure_utf8(css, field="stylesheet.css")

        def _compile() -> object:
            renderer = self._renderer_for_admitted_call()
            method = (
                renderer.compile_stylesheet_lossy
                if lossy
                else renderer.compile_stylesheet
            )
            return self._compiled.get_or_insert(
                ("css-lossy" if lossy else "css-strict", css),
                weight=utf8_weight(css),
                factory=lambda: method(css),
            )

        return await self.run(_compile)

    def _register_fonts_sync(
        self,
        registrations: Sequence[tuple[str | None, _FontSpec]],
    ) -> tuple[str, ...]:
        renderer = self._renderer_for_admitted_call()
        resolved_registrations = tuple(
            (spec.generated_source if source is None else source, spec)
            for source, spec in registrations
        )
        with self._font_lock:
            projected = dict(self._font_registrations)
            for source, spec in resolved_registrations:
                existing = projected.get(source)
                _validate_font_registration(source, spec, existing)
                if existing is None:
                    projected[source] = _FontRegistration(
                        digest=spec.digest,
                        options=spec.options,
                        families=(),
                    )

            result: list[str] = []
            for source, spec in resolved_registrations:
                existing = self._font_registrations.get(source)
                if existing is None:
                    families = tuple(renderer.register_font(spec.to_native()))
                    existing = _FontRegistration(
                        digest=spec.digest,
                        options=spec.options,
                        families=families,
                    )
                    self._font_registrations[source] = existing
                result.extend(existing.families)
            unique = tuple(dict.fromkeys(result))
            self.registered_font_families = tuple(
                dict.fromkeys((*self.registered_font_families, *unique))
            )
            return unique

    async def register_font(
        self,
        font: object,
        *,
        source: str | None = None,
    ) -> tuple[str, ...]:
        spec = _coerce_font_spec(font, field_name="font")
        if source is not None:
            ensure_utf8(source, field="font.source")
            if not source:
                raise TakumiInputError("font.source", "must not be empty")
        return await self.run(
            self._register_fonts_sync,
            ((source, spec),),
        )

    async def register_fonts(
        self,
        fonts: Sequence[object],
        *,
        sources: Sequence[str | None] | None = None,
    ) -> tuple[str, ...]:
        if sources is not None and len(sources) != len(fonts):
            raise ValueError("sources must contain one entry for each font")
        registrations: list[tuple[str | None, _FontSpec]] = []
        for index, font in enumerate(fonts):
            spec = _coerce_font_spec(font, field_name=f"fonts[{index}]")
            source = sources[index] if sources is not None else None
            if source is not None:
                ensure_utf8(source, field=f"fonts[{index}].source")
                if not source:
                    raise TakumiInputError(
                        f"fonts[{index}].source",
                        "must not be empty",
                    )
            registrations.append((source, spec))
        return await self.run(self._register_fonts_sync, tuple(registrations))

    async def register_font_file(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        weight: float | None = None,
        style: str | None = None,
        subset_of: str | None = None,
        generic_family: GenericFontFamily | None = None,
        cache_policy: FileCachePolicy,
    ) -> tuple[str, ...]:
        self._ensure_open()
        payload = await read_resource_bytes(path, policy=cache_policy)
        spec = _validate_font_spec(
            _FontSpec(
                data=payload,
                name=name,
                weight=weight,
                style=style,
                subset_of=subset_of,
                generic_family=generic_family,
            ),
            field_name="font",
        )
        return await self.run(
            self._register_fonts_sync,
            ((_font_source(path), spec),),
        )

    def _release_resources(self) -> None:
        """Drop native-backed cache, font, and renderer state in a worker."""

        self._compiled.clear()
        with self._font_lock:
            self._font_registrations.clear()
            self.registered_font_families = ()
        with self._lifecycle_lock:
            self.renderer = None

    async def aclose(self) -> None:
        owner = False
        with self._lifecycle_lock:
            if self._lifecycle == "closed":
                return
            if self._lifecycle == "open":
                self._lifecycle = "closing"
                owner = True

        with anyio.CancelScope(shield=True):
            if not owner:
                await run_sync(self._closed_event.wait)
                return
            await run_sync(self._drained.wait)
            try:
                await run_sync(self._release_resources)
                with self._lifecycle_lock:
                    self._lifecycle = "closed"
            finally:
                self._closed_event.set()


async def _load_font_payloads(
    fonts: Sequence[TakumiFontConfig],
    *,
    config: TakumiConfig,
) -> tuple[bytes, ...]:
    payloads: list[bytes | None] = [None] * len(fonts)

    async def _read_one(index: int, font: TakumiFontConfig) -> None:
        payloads[index] = await read_resource_bytes(
            font.path,
            policy=font.cache_policy or config.font_cache_policy,
        )

    async with anyio.create_task_group() as task_group:
        for index, font in enumerate(fonts):
            task_group.start_soon(_read_one, index, font)

    if any(payload is None for payload in payloads):
        raise TakumiRuntimeError("One or more configured fonts could not be loaded.")
    return cast("tuple[bytes, ...]", tuple(payloads))


def _normalize_images(
    images: Sequence[object] | None,
    *,
    field_name: str,
) -> tuple[TakumiImageResource, ...] | None:
    if images is None:
        return None

    return tuple(
        normalize_image_input(image, field=f"{field_name}[{index}]")
        for index, image in enumerate(images)
    )


def _prepare_call_kwargs(
    method_name: str,
    kwargs: dict[str, object],
) -> dict[str, object]:
    """Normalize pure-Python adapters and validate native-bound strings."""

    normalized = dict(kwargs)
    for name in ("images", "fetched_resources"):
        value = normalized.get(name)
        if value is not None:
            if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
                raise TypeError(f"{method_name}.{name} must be a sequence of images.")
            normalized[name] = _normalize_images(
                value,
                field_name=f"{method_name}.{name}",
            )
    for name, value in normalized.items():
        validate_native_strings(value, field=f"{method_name}.{name}")
    return normalized


def _to_native_call_kwargs(kwargs: dict[str, object]) -> dict[str, object]:
    """Construct takumi-py resource objects inside the admitted worker."""

    native = dict(kwargs)
    resource_names = tuple(
        name for name in ("images", "fetched_resources") if native.get(name) is not None
    )
    if not resource_names:
        return native

    from takumi_py import ImageResource  # noqa: PLC0415

    for name in resource_names:
        value = native.get(name)
        resources = cast("Sequence[TakumiImageResource]", value)
        native[name] = [
            ImageResource(
                resource.src,
                resource.data,
                cache=resource.cache,
            )
            for resource in resources
        ]
    return native


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
    """Create one renderer and register revalidated font bytes exactly once."""

    limiter = anyio.CapacityLimiter(config.max_concurrency)
    fonts = tuple(config.fonts)
    payloads = await _load_font_payloads(fonts, config=config) if fonts else ()
    specs = tuple(
        _validate_font_spec(
            _FontSpec(
                data=payload,
                name=font.name,
                weight=font.weight,
                style=font.style,
                subset_of=font.subset_of,
                generic_family=font.generic_family,
            ),
            field_name=f"fonts[{index}]",
        )
        for index, (font, payload) in enumerate(zip(fonts, payloads, strict=True))
    )
    sources = tuple(_font_source(font.path) for font in fonts)
    for index, spec in enumerate(specs):
        validate_native_strings(spec, field=f"fonts[{index}]")

    def _build() -> tuple[
        NativeRenderer,
        tuple[str, ...],
        dict[str, _FontRegistration],
    ]:
        from takumi_py import Renderer  # noqa: PLC0415

        renderer = Renderer(load_default_fonts=config.load_default_fonts)
        registrations: dict[str, _FontRegistration] = {}
        all_families: list[str] = []
        for source, spec in zip(sources, specs, strict=True):
            existing = registrations.get(source)
            _validate_font_registration(source, spec, existing)
            if existing is None:
                families = tuple(renderer.register_font(spec.to_native()))
                existing = _FontRegistration(
                    digest=spec.digest,
                    options=spec.options,
                    families=families,
                )
                registrations[source] = existing
            all_families.extend(existing.families)
        return (
            cast("NativeRenderer", renderer),
            tuple(dict.fromkeys(all_families)),
            registrations,
        )

    renderer, registered_families, registrations = await run_sync(
        _build,
        limiter=limiter,
    )
    state = TakumiRuntimeState(
        renderer=renderer,
        limiter=limiter,
        config=config.model_copy(deep=True),
        registered_font_families=registered_families,
    )
    state._font_registrations.update(registrations)
    return state


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
