"""Stable provider-specific capability contracts and lookup keys."""

from .playwright import PLAYWRIGHT_CAPABILITIES, PlaywrightCapability
from .takumi import TAKUMI_CAPABILITIES, TakumiCapability

__all__ = [
    "PLAYWRIGHT_CAPABILITIES",
    "TAKUMI_CAPABILITIES",
    "PlaywrightCapability",
    "TakumiCapability",
]
