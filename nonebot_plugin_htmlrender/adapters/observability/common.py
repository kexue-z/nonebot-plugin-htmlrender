from __future__ import annotations

from contextlib import suppress
import inspect
from typing import Callable, Mapping

from nonebot_plugin_htmlrender.consts import RenderBackend


def normalize_backend(backend: RenderBackend | str | None) -> str:
    """将后端标识规范化为字符串。

    Args:
        backend: 渲染后端标识，可以是枚举、字符串或 None。

    Returns:
        规范化后的后端名称字符串，None 时返回 "unknown"。
    """
    if backend is None:
        return "unknown"
    if isinstance(backend, RenderBackend):
        return backend.value
    return str(backend)


def metric_params(fn: Callable[..., object]) -> set[str]:
    """获取函数的参数名集合。

    通过 inspect.signature 提取函数参数名。这里不缓存结果，避免为观测适配器
    引入额外的进程级可变状态，也避免对象销毁后 ``id`` 复用造成错误命中。

    Args:
        fn: 要检查的函数。

    Returns:
        函数参数名的集合。
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
    """自适应调用遥测指标记录函数。

    根据目标函数的参数签名自动适配调用方式，支持 value/amount 等
    不同命名约定以及 tags/attributes 等不同标签参数。

    Args:
        fn: 指标记录函数。
        name: 指标名称。
        value: 指标值。
        unit: 指标单位，为 None 时不传递。
        tags: 指标标签字典。
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
    """为追踪 span 设置属性。

    优先使用 set_attribute 方法，回退到 set_data 方法，兼容不同追踪库的 API。

    Args:
        span: 追踪 span 对象。
        key: 属性键。
        value: 属性值。
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
    """设置追踪 span 的状态。

    Args:
        span: 追踪 span 对象。
        status: 状态字符串（如 "ok" 或 "error"）。
    """
    try:
        set_status = getattr(span, "set_status", None)
    except Exception:
        return
    if not callable(set_status):
        return
    with suppress(Exception):
        set_status(status)


def get_trace_id(span: object) -> str | None:
    """从追踪 span 中提取 trace ID 字符串。

    Args:
        span: 追踪 span 对象。

    Returns:
        trace ID 字符串，无法提取时返回 None。
    """
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
