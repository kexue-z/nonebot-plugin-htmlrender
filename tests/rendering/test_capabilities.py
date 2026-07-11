from __future__ import annotations

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
        CapabilityCatalog().with_capability(ECHO_KEY, _Other())  # type: ignore[arg-type]


def test_contains_rejects_non_key_objects() -> None:
    catalog = CapabilityCatalog().with_capability(ECHO_KEY, _Echo())

    assert "test.echo" not in catalog
