from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec

from nonebot_plugin_htmlrender.providers.sdk import ProviderAvailability

_SUPPORTED_TAKUMI_VERSION = "0.2.0"


def takumi_availability() -> ProviderAvailability:
    try:
        if find_spec("takumi_py") is None:
            return ProviderAvailability(
                available=False,
                reason="Optional dependency `takumi-py==0.2.0` is not installed.",
            )
    except (ImportError, ValueError) as error:
        return ProviderAvailability(
            available=False,
            reason=f"Cannot locate takumi_py: {error}",
        )

    try:
        installed_version = version("takumi-py")
    except PackageNotFoundError:
        return ProviderAvailability(
            available=False,
            reason="Distribution metadata for `takumi-py` is unavailable.",
        )
    if installed_version != _SUPPORTED_TAKUMI_VERSION:
        return ProviderAvailability(
            available=False,
            reason=(
                f"Unsupported takumi-py version {installed_version!r}; "
                f"expected {_SUPPORTED_TAKUMI_VERSION!r}."
            ),
        )

    return ProviderAvailability(available=True)


__all__ = ["takumi_availability"]
