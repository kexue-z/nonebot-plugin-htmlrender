"""Validation for values crossing the Python-to-Rust Takumi boundary."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import fields, is_dataclass

from .errors import TakumiInputError


def ensure_utf8(value: str, *, field: str) -> str:
    """Reject Python strings that cannot be encoded as strict UTF-8."""

    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise TakumiInputError(
            field,
            "must contain valid UTF-8 text "
            f"(unencodable code point at index {error.start})",
            source=error,
        ) from error
    return value


def ensure_native_identifier(value: str, *, field: str) -> str:
    """Validate text used as a native identifier or resource key."""

    ensure_utf8(value, field=field)
    if "\0" in value:
        raise TakumiInputError(field, "must not contain NUL characters")
    return value


def validate_native_strings(value: object, *, field: str) -> None:
    """Recursively validate every string in one native-call argument."""

    _validate_native_strings(value, field=field, seen=set())


def _validate_native_strings(
    value: object,
    *,
    field: str,
    seen: set[int],
) -> None:
    if isinstance(value, str):
        ensure_utf8(value, field=field)
        return
    if value is None or isinstance(value, (bytes, bytearray, memoryview)):
        return

    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        for index, (key, item) in enumerate(value.items()):
            if isinstance(key, str):
                ensure_native_identifier(key, field=f"{field}.keys[{index}]")
                item_field = f"{field}[{key!r}]"
            else:
                item_field = f"{field}.values[{index}]"
            _validate_native_strings(item, field=item_field, seen=seen)
        return

    if isinstance(value, Sequence):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        for index, item in enumerate(value):
            _validate_native_strings(item, field=f"{field}[{index}]", seen=seen)
        return

    if isinstance(value, AbstractSet):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        for index, item in enumerate(value):
            _validate_native_strings(item, field=f"{field}[{index}]", seen=seen)
        return

    if isinstance(value, Iterator):
        raise TakumiInputError(
            field,
            "must not be a one-shot iterator; materialize it before native use",
        )

    if is_dataclass(value) and not isinstance(value, type):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        for item in fields(value):
            _validate_native_strings(
                getattr(value, item.name),
                field=f"{field}.{item.name}",
                seen=seen,
            )


def utf8_weight(*values: str) -> int:
    """Return deterministic cache weight after validating the source strings."""

    return sum(
        len(ensure_utf8(value, field="compiled source").encode()) for value in values
    )


__all__ = [
    "ensure_native_identifier",
    "ensure_utf8",
    "utf8_weight",
    "validate_native_strings",
]
