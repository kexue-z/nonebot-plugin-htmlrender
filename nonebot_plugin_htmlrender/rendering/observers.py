"""Observer no-ops and the failure-containing observation wrapper."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, final

from nonebot.log import logger

from nonebot_plugin_htmlrender.resources.observation import (
    NoopCacheObserver as NoopCacheObserver,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from contextlib import AbstractContextManager

    from .ports import OperationObserver


@final
class NoopOperationObserver:
    """Observer that ignores every operation."""

    def observe(
        self,
        operation: str,  # noqa: ARG002 -- protocol-conforming no-op
        attributes: Mapping[str, str],  # noqa: ARG002 -- protocol-conforming no-op
    ) -> AbstractContextManager[None]:
        return nullcontext()


def _log_observer_failure(operation: str, error: Exception) -> None:
    logger.warning("Operation observer failed for {}: {}", operation, error)


@contextmanager
def observe_operation(
    observer: OperationObserver,
    operation: str,
    attributes: Mapping[str, str],
) -> Iterator[None]:
    """Run one operation under the observer, containing observer failures.

    Observer errors are logged and swallowed; errors from the observed body
    always propagate and are reported to the observer exactly once.
    """
    try:
        context = observer.observe(operation, attributes)
    except Exception as error:
        _log_observer_failure(operation, error)
        context = None

    entered = False
    if context is not None:
        try:
            context.__enter__()
            entered = True
        except Exception as error:
            _log_observer_failure(operation, error)

    try:
        yield
    except BaseException as error:
        if entered and context is not None:
            try:
                context.__exit__(type(error), error, error.__traceback__)
            except Exception as exit_error:
                _log_observer_failure(operation, exit_error)
        raise
    if entered and context is not None:
        try:
            context.__exit__(None, None, None)
        except Exception as error:
            _log_observer_failure(operation, error)
