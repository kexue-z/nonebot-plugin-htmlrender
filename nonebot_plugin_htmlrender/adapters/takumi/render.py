from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec

from nonebot_plugin_htmlrender.adapters._backend import BackendAvailability

_SUPPORTED_TAKUMI_VERSION = "0.2.0"


def is_takumi_backend_available() -> BackendAvailability:
    try:
        if find_spec("takumi_py") is None:
            return BackendAvailability(
                available=False,
                reason="Optional dependency `takumi-py==0.2.0` is not installed.",
            )
    except (ImportError, ValueError) as error:
        return BackendAvailability(
            available=False,
            reason=f"Cannot locate takumi_py: {error}",
        )

    try:
        installed_version = version("takumi-py")
    except PackageNotFoundError:
        return BackendAvailability(
            available=False,
            reason="Distribution metadata for `takumi-py` is unavailable.",
        )
    if installed_version != _SUPPORTED_TAKUMI_VERSION:
        return BackendAvailability(
            available=False,
            reason=(
                f"Unsupported takumi-py version {installed_version!r}; "
                f"expected {_SUPPORTED_TAKUMI_VERSION!r}."
            ),
        )

    return BackendAvailability(available=True)


__all__ = ["is_takumi_backend_available"]
