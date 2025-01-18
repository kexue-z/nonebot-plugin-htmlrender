from functools import wraps
from typing import (
    Any,
    Callable,
    Optional,
    TypeVar,
    Union,
    overload,
)
from typing_extensions import ParamSpec
import warnings

P = ParamSpec("P")
R = TypeVar("R")
F = TypeVar("F", bound=Callable[..., Any])


@overload
def deprecated(func: Callable[P, R]) -> Callable[P, R]: ...


@overload
def deprecated(
    func: None = None,
    *,
    message: Optional[str] = None,
    version: Optional[str] = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def deprecated(
    func: Optional[Callable[P, R]] = None,
    *,
    message: Optional[str] = None,
    version: Optional[str] = None,
) -> Union[Callable[P, R], Callable[[Callable[P, R]], Callable[P, R]]]:
    """
    一个用于标记函数为已废弃的装饰器。

    可以通过两种方式使用：
    1. 作为简单装饰器：@deprecated
    2. 带参数的方式：@deprecated(message="...", version="...")

    参数：
        func: 需要标记为废弃的函数
        message: 自定义的废弃提示消息（可选）
        version: 函数被废弃时的版本号（可选）

    示例：
        >>> @deprecated
        ... def old_function():
        ...     pass

        >>> @deprecated(message="请使用 new_function() 代替", version="2.0.0")
        ... def another_old_function():
        ...     pass
    """

    def create_wrapper(f: Callable[P, R]) -> Callable[P, R]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            warning_message = message or f"函数 '{f.__name__}' 已废弃。"
            if version:
                warning_message += f" (在版本 {version} 中被标记为废弃)"

            warnings.warn(warning_message, category=DeprecationWarning, stacklevel=2)
            return f(*args, **kwargs)

        return wrapper

    return create_wrapper if func is None else create_wrapper(func)
