from __future__ import annotations

from typing import Any, Protocol, cast

import pytest

from nonebot_plugin_htmlrender.rendering import (
    CapabilityCatalog,
    CapabilityKey,
    CapabilityUnavailable,
)


class _Echo:
    def shout(self) -> str:
        return "echo"


class _Other:
    pass


class _StructuralCapability(Protocol):
    def ping(self) -> str: ...


ECHO_KEY = CapabilityKey("test.echo", _Echo)


def test_empty_catalog_reports_missing_capability() -> None:
    catalog = CapabilityCatalog()

    assert catalog.get(ECHO_KEY) is None
    assert ECHO_KEY not in catalog
    assert catalog.names() == frozenset()
    with pytest.raises(CapabilityUnavailable) as exc_info:
        catalog.require(ECHO_KEY)
    assert exc_info.value.capability == "test.echo"


def test_with_capability_returns_new_catalog_and_typed_value() -> None:
    empty = CapabilityCatalog()
    echo = _Echo()

    catalog = empty.with_capability(ECHO_KEY, echo)

    assert catalog.require(ECHO_KEY) is echo
    assert catalog.require(ECHO_KEY).shout() == "echo"
    assert ECHO_KEY in catalog
    assert catalog.names() == frozenset({"test.echo"})
    # The original catalog is unchanged.
    assert ECHO_KEY not in empty


def test_duplicate_capability_name_rejected() -> None:
    catalog = CapabilityCatalog().with_capability(ECHO_KEY, _Echo())

    with pytest.raises(ValueError, match="already registered"):
        catalog.with_capability(ECHO_KEY, _Echo())


def test_registration_validates_interface() -> None:
    with pytest.raises(TypeError, match="expects _Echo"):
        CapabilityCatalog().with_capability(ECHO_KEY, cast("Any", _Other()))


def test_registration_diagnoses_non_runtime_protocol() -> None:
    key = CapabilityKey("test.structural", _StructuralCapability)

    with pytest.raises(TypeError, match="runtime_checkable"):
        CapabilityCatalog().with_capability(key, cast("Any", _Other()))


def test_get_rejects_same_name_key_with_incompatible_interface() -> None:
    # A different key can share the registered name but demand another
    # interface; the lookup must not hand back the wrong-typed value.
    conflicting_key = CapabilityKey("test.echo", _Other)
    catalog = CapabilityCatalog().with_capability(ECHO_KEY, _Echo())

    with pytest.raises(CapabilityUnavailable, match="not _Other"):
        catalog.get(conflicting_key)
    with pytest.raises(CapabilityUnavailable, match="not _Other"):
        catalog.require(conflicting_key)


def test_contains_rejects_non_key_objects() -> None:
    catalog = CapabilityCatalog().with_capability(ECHO_KEY, _Echo())

    assert "test.echo" not in catalog


def test_catalog_merges_disjoint_composition_capabilities() -> None:
    other_key = CapabilityKey("test.other", _Echo)
    first = _Echo()
    second = _Echo()

    merged = (
        CapabilityCatalog()
        .with_capability(ECHO_KEY, first)
        .merged(CapabilityCatalog().with_capability(other_key, second))
    )

    assert merged.require(ECHO_KEY) is first
    assert merged.require(other_key) is second


def test_catalog_rejects_duplicate_names_when_merging() -> None:
    left = CapabilityCatalog().with_capability(ECHO_KEY, _Echo())
    right = CapabilityCatalog().with_capability(ECHO_KEY, _Echo())

    with pytest.raises(ValueError, match=r"test\.echo"):
        left.merged(right)
