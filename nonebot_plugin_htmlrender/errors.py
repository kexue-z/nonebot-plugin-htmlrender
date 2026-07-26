"""Lowest-level public error root shared by all architectural layers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import final

from exceptiongroup import BaseExceptionGroup

_MAX_MESSAGE_LENGTH = 512
_MAX_CAUSE_MESSAGE_LENGTH = 256
_MAX_EXCEPTION_TYPE_LENGTH = 96
_MAX_CAUSES = 3
_ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _clip_text(value: str, limit: int) -> tuple[str, bool]:
    normalized = " ".join(_ANSI_ESCAPE.sub("", value).split())
    if len(normalized) <= limit:
        return normalized, False
    return f"{normalized[: limit - 1].rstrip()}…", True


@final
@dataclass(frozen=True, slots=True)
class ErrorCause:
    """Bounded information copied from one underlying exception."""

    exception_type: str
    message: str
    truncated: bool = False


def _capture_cause(error: BaseException, message: str | None = None) -> ErrorCause:
    exception_type, type_truncated = _clip_text(
        type(error).__name__,
        _MAX_EXCEPTION_TYPE_LENGTH,
    )
    detail, message_truncated = _clip_text(
        str(error) if message is None else message,
        _MAX_CAUSE_MESSAGE_LENGTH,
    )
    return ErrorCause(
        exception_type=exception_type,
        message=detail,
        truncated=type_truncated or message_truncated,
    )


def _captured_causes(error: BaseException) -> tuple[tuple[ErrorCause, ...], bool]:
    if isinstance(error, _DetailedError) and error.causes:
        return error.causes, error.causes_truncated

    pending: list[BaseException] = [error]
    causes: list[ErrorCause] = []
    causes_truncated = False
    seen: set[int] = set()
    while pending and len(causes) < _MAX_CAUSES:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        if isinstance(current, BaseExceptionGroup):
            causes.append(_capture_cause(current, current.message))
            pending.extend(reversed(current.exceptions))
            continue
        if isinstance(current, _DetailedError) and current.causes:
            available = _MAX_CAUSES - len(causes)
            causes.extend(current.causes[:available])
            if current.causes_truncated or len(current.causes) > available:
                causes_truncated = True
            continue
        causes.append(_capture_cause(current))
        nested = current.__cause__
        if nested is None and not current.__suppress_context__:
            nested = current.__context__
        if nested is not None:
            pending.append(nested)
    return tuple(causes), causes_truncated or bool(pending)


class _DetailedError(Exception):
    message: str
    message_truncated: bool
    causes: tuple[ErrorCause, ...]
    causes_truncated: bool

    def __init__(
        self,
        message: str,
        *,
        source: BaseException | None = None,
    ) -> None:
        self.message, self.message_truncated = _clip_text(
            message,
            _MAX_MESSAGE_LENGTH,
        )
        if source is None:
            self.causes = ()
            self.causes_truncated = False
        else:
            self.causes, self.causes_truncated = _captured_causes(source)
        super().__init__(self._display_message())

    def _display_message(self) -> str:
        if not self.causes:
            return self.message
        details = "; ".join(
            (
                f"{cause.exception_type}: {cause.message}"
                if cause.message
                else cause.exception_type
            )
            for cause in self.causes
        )
        if self.causes_truncated:
            details = f"{details}; …"
        return f"{self.message} Caused by {details}"


class RenderingError(_DetailedError):
    """Base class for stable errors exposed by the rendering application."""


class InvalidRenderRequest(RenderingError):
    """A public operation received values that cannot be processed."""


class PreparationError(RenderingError):
    """Backend-neutral content preparation failed."""


__all__ = [
    "ErrorCause",
    "InvalidRenderRequest",
    "PreparationError",
    "RenderingError",
]
