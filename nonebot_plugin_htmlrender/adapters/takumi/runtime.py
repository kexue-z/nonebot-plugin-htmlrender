from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from functools import partial
from hashlib import sha256
import math
from pathlib import Path
import threading
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeGuard, TypeVar

import anyio
from anyio.to_thread import run_sync

from nonebot_plugin_htmlrender.resources.observation import NoopCacheObserver

from .cache import SyncWeightedSingleflightLRU, WeightedCacheStats
from .config import FileCachePolicy
from .errors import TakumiInputError, TakumiRuntimeError
from .source import normalize_image_input
from .types import TakumiImageResource
from .validation import (
    ensure_native_identifier,
    ensure_utf8,
    utf8_weight,
    validate_native_strings,
)

if TYPE_CHECKING:
    from takumi_py import FontResourceInput

    from nonebot_plugin_htmlrender.resources.observation import CacheObserver
    from nonebot_plugin_htmlrender.resources.ports import ProviderResources

    from .config import GenericFontFamily, TakumiConfig, TakumiFontConfig
    from .types import NativeCompiledHtml, NativeRenderer

T = TypeVar("T")
R_co = TypeVar("R_co", covariant=True)
P = ParamSpec("P")
_MISSING = object()

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


def _is_generic_font_family(value: str) -> TypeGuard[GenericFontFamily]:
    return value in _GENERIC_FONT_FAMILIES


class _RendererMethod(Protocol[P, R_co]):
    @property
    def __name__(self) -> str: ...

    def __call__(
        self,
        renderer: NativeRenderer,
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R_co: ...


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


@dataclass(frozen=True, slots=True)
class _CompiledHtmlCacheValue:
    value: NativeCompiledHtml


@dataclass(frozen=True, slots=True)
class _CompiledStylesheetCacheValue:
    value: object


def _validate_font_spec(spec: _FontSpec, *, field_name: str) -> _FontSpec:
    for attribute, value in (
        ("name", spec.name),
        ("style", spec.style),
        ("subset_of", spec.subset_of),
        ("generic_family", spec.generic_family),
    ):
        if value is not None:
            ensure_native_identifier(value, field=f"{field_name}.{attribute}")
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


def _optional_identifier(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None, got {type(value).__name__}.")
    return ensure_native_identifier(value, field=field)


def _optional_generic_family(
    value: object,
    *,
    field: str,
) -> GenericFontFamily | None:
    normalized = _optional_identifier(value, field=field)
    if normalized is None:
        return None
    if not _is_generic_font_family(normalized):
        raise TakumiInputError(field, f"unsupported generic font family {normalized!r}")
    return normalized


def _coerce_font_spec(font: object, *, field_name: str) -> _FontSpec:
    if isinstance(font, bytes):
        return _FontSpec(data=font)
    values = tuple(
        getattr(font, attribute, _MISSING)
        for attribute in (
            "data",
            "name",
            "weight",
            "style",
            "subset_of",
            "generic_family",
        )
    )
    if any(value is _MISSING for value in values):
        raise TypeError(
            f"{field_name} must be bytes or expose FontResource-compatible fields."
        )
    data, raw_name, weight, raw_style, raw_subset_of, raw_generic_family = values
    if not isinstance(data, bytes):
        raise TypeError(f"{field_name}.data must be bytes, got {type(data).__name__}.")
    name = _optional_identifier(raw_name, field=f"{field_name}.name")
    style = _optional_identifier(raw_style, field=f"{field_name}.style")
    subset_of = _optional_identifier(raw_subset_of, field=f"{field_name}.subset_of")
    generic_family = _optional_generic_family(
        raw_generic_family,
        field=f"{field_name}.generic_family",
    )
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
    limiter: anyio.Semaphore
    config: TakumiConfig
    resources: ProviderResources
    registered_font_families: tuple[str, ...] = ()
    cache_observer: CacheObserver | None = None
    _compiled: SyncWeightedSingleflightLRU[
        tuple[object, ...],
        _CompiledHtmlCacheValue | _CompiledStylesheetCacheValue,
    ] = field(
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
    _poisoned: threading.Event = field(
        default_factory=threading.Event,
        init=False,
        repr=False,
    )
    _closed_flag: bool = field(default=False, init=False, repr=False)
    _font_registrations: dict[str, _FontRegistration] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        observer = (
            self.cache_observer
            if self.cache_observer is not None
            else NoopCacheObserver()
        )
        self._compiled = SyncWeightedSingleflightLRU(
            max_entries=self.config.compiled_cache_max_entries,
            max_weight=self.config.compiled_cache_max_source_bytes,
            observer=observer,
            cache_name="takumi_compiled",
        )

    @property
    def closed(self) -> bool:
        with self._lifecycle_lock:
            return self._closed_flag

    @property
    def healthy(self) -> bool:
        """False once a native panic may have corrupted the runtime."""
        return not self._poisoned.is_set()

    def _mark_poisoned(self) -> None:
        self._poisoned.set()

    @property
    def compiled_cache_stats(self) -> WeightedCacheStats:
        return self._compiled.stats()

    def _ensure_open(self) -> None:
        with self._lifecycle_lock:
            if self._closed_flag:
                raise TakumiRuntimeError(
                    "Takumi runtime is closed; new calls are rejected."
                )

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
        self,
        func: Callable[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """Run one native call under the concurrency limiter.

        Drain-before-close is owned by the shared ``ExecutionLeaseProvider``;
        this state only rejects calls after ``aclose`` and lets in-flight
        calls finish on the renderer reference they already hold.
        """
        self._ensure_open()
        operation = getattr(func, "__name__", type(func).__name__)
        async with self.limiter:
            return await run_sync(
                partial(
                    _invoke_native,
                    operation,
                    partial(func, *args, **kwargs),
                    on_panic=self._mark_poisoned,
                )
            )

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

    async def invoke_renderer(
        self,
        method: _RendererMethod[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """Invoke one statically selected native renderer method."""
        method_name = method.__name__
        normalized_kwargs = _prepare_call_kwargs(method_name, dict(kwargs))
        for index, value in enumerate(args):
            validate_native_strings(
                value,
                field=f"{method_name}.args[{index}]",
            )

        def _invoke() -> T:
            renderer = self._renderer_for_admitted_call()
            return _invoke_renderer_method(
                method,
                renderer,
                tuple(args),
                _to_native_call_kwargs(normalized_kwargs),
            )

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
        compiled_html_entry = self._compiled.get_or_insert(
            ("html", html, *options_key),
            weight=utf8_weight(
                html,
                options.presets,
                options.tailwind_property or "",
            ),
            factory=lambda: _CompiledHtmlCacheValue(
                renderer.compile_html(
                    html,
                    html_options=html_options,
                )
            ),
        )
        if not isinstance(compiled_html_entry, _CompiledHtmlCacheValue):
            raise TakumiRuntimeError("Compiled cache returned an invalid HTML entry.")
        compiled_stylesheet_entries = tuple(
            self._compiled.get_or_insert(
                ("css-lossy", css),
                weight=utf8_weight(css),
                factory=lambda css=css: _CompiledStylesheetCacheValue(
                    renderer.compile_stylesheet_lossy(css)
                ),
            )
            for css in stylesheets
        )
        if any(
            not isinstance(entry, _CompiledStylesheetCacheValue)
            for entry in compiled_stylesheet_entries
        ):
            raise TakumiRuntimeError(
                "Compiled cache returned an invalid stylesheet entry."
            )
        return (
            compiled_html_entry.value.node,
            tuple(entry.value for entry in compiled_stylesheet_entries),
        )

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
            entry = self._compiled.get_or_insert(
                ("css-lossy" if lossy else "css-strict", css),
                weight=utf8_weight(css),
                factory=lambda: _CompiledStylesheetCacheValue(method(css)),
            )
            if not isinstance(entry, _CompiledStylesheetCacheValue):
                raise TakumiRuntimeError(
                    "Compiled cache returned an invalid stylesheet entry."
                )
            return entry.value

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
            ensure_native_identifier(source, field="font.source")
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
                ensure_native_identifier(source, field=f"fonts[{index}].source")
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
        payload = await self.resources.read_bytes(
            path,
            refresh=cache_policy is FileCachePolicy.REVALIDATE,
        )
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
        with self._lifecycle_lock:
            if self._closed_flag:
                return
            self._closed_flag = True
        with anyio.CancelScope(shield=True):
            await run_sync(self._release_resources)


def _is_panic(error: BaseException) -> bool:
    return (
        type(error).__module__ == "pyo3_runtime"
        and type(error).__name__ == "PanicException"
    )


def _is_native_error(error: BaseException) -> bool:
    import takumi_py  # noqa: PLC0415

    native_error = getattr(takumi_py, "TakumiError", ())
    return isinstance(error, native_error) or _is_panic(error)


def _invoke_native(
    operation: str,
    func: Callable[[], T],
    *,
    on_panic: Callable[[], None] | None = None,
) -> T:
    try:
        return func()
    except BaseException as error:
        if on_panic is not None and _is_panic(error):
            on_panic()
        if _is_native_error(error):
            raise TakumiRuntimeError(
                f"Takumi native operation {operation!r} failed.",
                source=error,
            ) from error
        raise


def _invoke_renderer_method(
    method: Callable[..., T],
    renderer: NativeRenderer,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> T:
    """Cross the validated dynamic-call boundary without losing the return type."""
    return method(renderer, *args, **kwargs)


async def _load_font_payloads(
    fonts: Sequence[TakumiFontConfig],
    *,
    config: TakumiConfig,
    resources: ProviderResources,
) -> tuple[bytes, ...]:
    payloads: list[bytes | None] = [None] * len(fonts)

    async def _read_one(index: int, font: TakumiFontConfig) -> None:
        policy = font.cache_policy or config.font_cache_policy
        payloads[index] = await resources.read_bytes(
            font.path,
            refresh=policy is FileCachePolicy.REVALIDATE,
        )

    async with anyio.create_task_group() as task_group:
        for index, font in enumerate(fonts):
            task_group.start_soon(_read_one, index, font)

    resolved = tuple(payload for payload in payloads if payload is not None)
    if len(resolved) != len(payloads):
        raise TakumiRuntimeError("One or more configured fonts could not be loaded.")
    return resolved


def _release_native_renderer(renderer: object) -> None:
    """Best-effort release of a native renderer during failed construction.

    The native handle is normally reclaimed on drop; this makes the release
    deterministic when it exposes an explicit close/shutdown/release method.
    """
    for method_name in ("close", "shutdown", "release"):
        method = getattr(renderer, method_name, None)
        if callable(method):
            with suppress(Exception):
                method()
            return


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


def _is_normalized_images(
    value: object,
) -> TypeGuard[Sequence[TakumiImageResource]]:
    return (
        not isinstance(value, (str, bytes))
        and isinstance(value, Sequence)
        and all(isinstance(resource, TakumiImageResource) for resource in value)
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
    lang = normalized.get("lang")
    if isinstance(lang, str):
        ensure_native_identifier(lang, field=f"{method_name}.lang")
    font_families = normalized.get("font_families")
    if isinstance(font_families, Sequence) and not isinstance(
        font_families,
        (str, bytes),
    ):
        for index, family in enumerate(font_families):
            if isinstance(family, str):
                ensure_native_identifier(
                    family,
                    field=f"{method_name}.font_families[{index}]",
                )
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
        if not _is_normalized_images(value):
            raise TakumiRuntimeError(
                f"Prepared {name} values lost their normalized image contract."
            )
        native[name] = [
            ImageResource(
                resource.src,
                resource.data,
                cache=resource.cache,
            )
            for resource in value
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


async def create_runtime_state(
    config: TakumiConfig,
    *,
    resources: ProviderResources,
    cache_observer: CacheObserver | None = None,
) -> TakumiRuntimeState:
    """Create one renderer and register revalidated font bytes exactly once."""

    limiter = anyio.Semaphore(config.max_concurrency)
    fonts = tuple(config.fonts)
    payloads = (
        await _load_font_payloads(fonts, config=config, resources=resources)
        if fonts
        else ()
    )
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
        try:
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
        except BaseException:
            # Font registration failed after the native renderer was created;
            # release it now so a failed lease creation cannot leak the handle.
            _release_native_renderer(renderer)
            raise
        return (
            renderer,
            tuple(dict.fromkeys(all_families)),
            registrations,
        )

    async with limiter:
        renderer, registered_families, registrations = await run_sync(
            _invoke_native,
            "create_runtime",
            _build,
        )
    state = TakumiRuntimeState(
        renderer=renderer,
        limiter=limiter,
        config=config.model_copy(deep=True),
        resources=resources,
        registered_font_families=registered_families,
        cache_observer=cache_observer,
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
