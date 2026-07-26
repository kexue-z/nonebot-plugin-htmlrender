"""Stable rendering error taxonomy and bounded cause snapshots."""

from __future__ import annotations

from exceptiongroup import ExceptionGroup

from nonebot_plugin_htmlrender.rendering import (
    ApplicationNotInitialized,
    CapabilityUnavailable,
    ErrorCause,
    InvalidRenderRequest,
    PreparationError,
    ProviderExecutionError,
    ProviderLifecycleError,
    ProviderNotFound,
    ProviderUnavailable,
    RenderingError,
    ResourceAccessDenied,
    ResourceNotFound,
    ResourceResolutionError,
    ResourceSizeExceeded,
    UnsupportedRenderOption,
    UnsupportedRequirement,
)


def test_error_taxonomy_roots_at_rendering_error() -> None:
    for error_type in (
        ApplicationNotInitialized,
        InvalidRenderRequest,
        PreparationError,
        CapabilityUnavailable,
        UnsupportedRenderOption,
        UnsupportedRequirement,
        ProviderNotFound,
        ProviderUnavailable,
        ProviderExecutionError,
        ProviderLifecycleError,
        ResourceResolutionError,
    ):
        assert issubclass(error_type, RenderingError)
    for error_type in (ResourceAccessDenied, ResourceNotFound, ResourceSizeExceeded):
        assert issubclass(error_type, ResourceResolutionError)


def test_rendering_error_captures_bounded_structured_cause() -> None:
    source = RuntimeError(f"\x1b[31mnative\x1b[0m\n{'x' * 300}")

    error = ProviderExecutionError("  Provider   failed.  ", source=source)

    assert error.message == "Provider failed."
    assert error.causes == (
        ErrorCause(
            exception_type="RuntimeError",
            message=f"native {'x' * 248}…",
            truncated=True,
        ),
    )
    assert not error.message_truncated
    assert not error.causes_truncated
    assert "\x1b" not in str(error)
    assert not hasattr(error, "source")


def test_rendering_error_flattens_and_limits_exception_groups() -> None:
    source = ExceptionGroup(
        "native failures",
        [ValueError(str(index)) for index in range(5)],
    )

    error = ProviderLifecycleError("Startup failed.", source=source)

    assert error.causes == (
        ErrorCause("ExceptionGroup", "native failures"),
        ErrorCause("ValueError", "0"),
        ErrorCause("ValueError", "1"),
    )
    assert error.causes_truncated
    assert str(error).endswith("ValueError: 1; …")


def test_rendering_error_reuses_already_cropped_leaf_causes() -> None:
    inner = PreparationError("Preparation failed.", source=ValueError("invalid"))

    outer = ProviderExecutionError("Render failed.", source=inner)

    assert outer.causes is inner.causes
    assert str(outer) == "Render failed. Caused by ValueError: invalid"


def test_rendering_error_preserves_bounded_native_cause_chain() -> None:
    native = OSError("connection refused")
    wrapper = RuntimeError("browser startup failed")
    wrapper.__cause__ = native

    error = ProviderLifecycleError("Startup failed.", source=wrapper)

    assert error.causes == (
        ErrorCause("RuntimeError", "browser startup failed"),
        ErrorCause("OSError", "connection refused"),
    )
