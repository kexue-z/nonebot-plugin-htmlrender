class TakumiBackendError(RuntimeError):
    """Base error raised by the htmlrender Takumi adapter."""


class TakumiRuntimeError(TakumiBackendError):
    """The Takumi runtime or session is unavailable."""


class TakumiUnsupportedError(TakumiBackendError):
    """The request requires browser behavior that Takumi cannot provide."""


class TakumiResourceError(TakumiBackendError):
    """A resource reference was not supplied as in-process bytes."""


__all__ = [
    "TakumiBackendError",
    "TakumiResourceError",
    "TakumiRuntimeError",
    "TakumiUnsupportedError",
]
