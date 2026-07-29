from __future__ import annotations

from contextlib import suppress
from importlib.util import find_spec
import inspect
import sys
import threading
from typing import TYPE_CHECKING, final

from nonebot import require
from nonebot.log import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import ModuleType

    from nonebot_plugin_htmlrender.providers.sdk import EngineId


@final
class OptionalPluginLoader:
    """Load one optional NoneBot plugin at most once and cache the outcome.

    Discovery, ``require`` bootstrap, and the resulting module lookup are
    serialized; failures are cached so a broken optional integration is
    probed exactly once per process.
    """

    def __init__(self, *, plugin: str, module: str) -> None:
        self._plugin = plugin
        self._module = module
        self._lock = threading.RLock()
        self._checked = False
        self._loaded: ModuleType | None = None

    def load(self, *, reason: str) -> ModuleType | None:
        with self._lock:
            if self._checked:
                return self._loaded
            self._checked = True
            self._loaded = self._bootstrap(reason)
            return self._loaded

    def _bootstrap(self, reason: str) -> ModuleType | None:
        try:
            installed = find_spec(self._plugin) is not None
        except Exception as error:
            logger.opt(colors=True).warning(
                "<d>[htmlrender.telemetry]</d> Cannot locate {plugin} "
                "({reason}): <r>{error}</r>.",
                plugin=self._plugin,
                reason=reason,
                error=error,
            )
            return None
        if not installed:
            logger.opt(colors=True).debug(
                "<d>[htmlrender.telemetry]</d> {plugin} not installed, "
                "skip bootstrap ({reason}).",
                plugin=self._plugin,
                reason=reason,
            )
            return None

        try:
            require(self._plugin)
        except Exception as error:
            logger.opt(colors=True).warning(
                "<d>[htmlrender.telemetry]</d> {plugin} bootstrap failed "
                "({reason}): <r>{error}</r>.",
                plugin=self._plugin,
                reason=reason,
                error=error,
            )
            return None

        module = sys.modules.get(self._module)
        if module is None:
            logger.opt(colors=True).warning(
                "<d>[htmlrender.telemetry]</d> {plugin} bootstrap incomplete "
                "({reason}): `{module}` module not found after require.",
                plugin=self._plugin,
                reason=reason,
                module=self._module,
            )
            return None

        logger.opt(colors=True).debug(
            "<d>[htmlrender.telemetry]</d> {plugin} bootstrap ready ({reason}).",
            plugin=self._plugin,
            reason=reason,
        )
        return module


def normalize_backend(backend: EngineId | None) -> str:
    """Normalize an open provider identifier into a metric label string."""
    if backend is None:
        return "unknown"
    return str(backend)


def metric_params(fn: Callable[..., object]) -> set[str]:
    """Return the parameter names of ``fn``.

    The result is deliberately not cached: caching would add process-level
    mutable state to the observability adapter, and ``id`` reuse after object
    destruction could produce false hits.
    """
    try:
        return set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return set()


def call_metric(
    fn: Callable[..., object],
    name: str,
    value: float | int,
    *,
    unit: str | None,
    tags: Mapping[str, str],
) -> None:
    """Invoke a metric recorder while adapting to its parameter naming.

    Supports the ``value``/``amount`` conventions for the metric value and
    the ``tags``/``attributes`` conventions for labels.
    """
    params = metric_params(fn)
    kwargs: dict[str, object] = {}
    if "unit" in params and unit is not None:
        kwargs["unit"] = unit
    if "tags" in params:
        kwargs["tags"] = dict(tags)
    if "attributes" in params:
        kwargs["attributes"] = dict(tags)

    if "value" in params:
        kwargs["value"] = value
        fn(name, **kwargs)
        return
    if "amount" in params:
        kwargs["amount"] = value
        fn(name, **kwargs)
        return

    fn(name, value, **kwargs)


def set_span_attribute(span: object, key: str, value: object) -> None:
    """Set one attribute on a tracing span.

    Prefers ``set_attribute`` and falls back to ``set_data`` so both
    OpenTelemetry-style and Sentry-style span APIs are supported.
    """
    try:
        set_attribute = getattr(span, "set_attribute", None)
    except Exception:
        set_attribute = None
    if callable(set_attribute):
        with suppress(Exception):
            set_attribute(key, value)
            return

    try:
        set_data = getattr(span, "set_data", None)
    except Exception:
        set_data = None
    if callable(set_data):
        with suppress(Exception):
            set_data(key, value)


def set_span_status(span: object, status: str) -> None:
    """Set the status string (for example ``ok`` or ``error``) on a span."""
    try:
        set_status = getattr(span, "set_status", None)
    except Exception:
        return
    if not callable(set_status):
        return
    with suppress(Exception):
        set_status(status)


def get_trace_id(span: object) -> str | None:
    """Extract the trace id string from a tracing span, if available."""
    try:
        trace_id = getattr(span, "trace_id", None)
    except Exception:
        return None
    if isinstance(trace_id, str):
        return trace_id or None

    try:
        to_string = getattr(trace_id, "to_string", None)
    except Exception:
        return None
    if not callable(to_string):
        return None
    with suppress(Exception):
        trace_value = to_string()
        if isinstance(trace_value, str):
            return trace_value
        return str(trace_value)
    return None
