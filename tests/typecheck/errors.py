"""Static probes for structured public rendering failures."""

from typing_extensions import assert_type

from nonebot_plugin_htmlrender import ErrorCause, RenderingError


def _probe(error: RenderingError) -> None:
    assert_type(error.message, str)
    assert_type(error.message_truncated, bool)
    causes = assert_type(error.causes, tuple[ErrorCause, ...])
    assert_type(error.causes_truncated, bool)
    for cause in causes:
        assert_type(cause.exception_type, str)
        assert_type(cause.message, str)
        assert_type(cause.truncated, bool)
