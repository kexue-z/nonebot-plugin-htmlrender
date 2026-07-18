"""Stable provider-specific capability contracts and lookup keys."""

from .playwright import (
    PLAYWRIGHT_CAPTURE,
    PLAYWRIGHT_PAGE,
    CaptureElementKwargs,
    GotoKwargs,
    LocatorScreenshotKwargs,
    PageContextKwargs,
    PlaywrightCaptureCapability,
    PlaywrightPageCapability,
)
from .takumi import TAKUMI_CAPABILITIES, TakumiCapability

__all__ = [
    "PLAYWRIGHT_CAPTURE",
    "PLAYWRIGHT_PAGE",
    "TAKUMI_CAPABILITIES",
    "CaptureElementKwargs",
    "GotoKwargs",
    "LocatorScreenshotKwargs",
    "PageContextKwargs",
    "PlaywrightCaptureCapability",
    "PlaywrightPageCapability",
    "TakumiCapability",
]
