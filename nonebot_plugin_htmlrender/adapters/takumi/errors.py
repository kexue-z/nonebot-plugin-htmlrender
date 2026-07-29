from nonebot_plugin_htmlrender.errors import RenderingError


class TakumiBackendError(RenderingError, RuntimeError):
    """Base error raised by the htmlrender Takumi adapter."""


class TakumiInputError(TakumiBackendError):
    """A field cannot be represented safely by the native Takumi boundary."""

    def __init__(
        self,
        field: str,
        message: str,
        *,
        source: BaseException | None = None,
    ) -> None:
        self.field = field
        super().__init__(f"Invalid Takumi field {field!r}: {message}", source=source)


class TakumiRuntimeError(TakumiBackendError):
    """The Takumi runtime or session is unavailable."""


class TakumiUnsupportedError(TakumiBackendError):
    """The request requires browser behavior that Takumi cannot provide."""


class TakumiResourceError(TakumiBackendError):
    """A resource reference was not supplied as in-process bytes."""


__all__ = [
    "TakumiBackendError",
    "TakumiInputError",
    "TakumiResourceError",
    "TakumiRuntimeError",
    "TakumiUnsupportedError",
]
