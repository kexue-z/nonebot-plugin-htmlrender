"""Shared request-header capability merge semantics."""

from __future__ import annotations

import pytest

from nonebot_plugin_htmlrender.resources.headers import (
    RequestHeaderConflict,
    combine_request_capabilities,
    merge_request_headers,
)


def test_capability_overrides_caller_preset_case_insensitively() -> None:
    preset = {"x-htmlrender-filehost-request": "wrong", "accept": "*/*"}
    capability = {"X-HTMLRender-Filehost-Request": "right"}

    merged = merge_request_headers(preset, capability)

    assert merged == {
        "accept": "*/*",
        "X-HTMLRender-Filehost-Request": "right",
    }


def test_capability_combination_dedupes_and_rejects_conflicts() -> None:
    combined = combine_request_capabilities(
        {"X-Guard": "token"},
        {"x-guard": "token", "X-Extra": "1"},
    )
    assert combined == {"X-Guard": "token", "X-Extra": "1"}

    with pytest.raises(RequestHeaderConflict):
        combine_request_capabilities({"X-Guard": "token"}, {"x-guard": "other"})
