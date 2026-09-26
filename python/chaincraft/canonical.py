"""Canonical JSON — SPEC/wire-v1.md section 1.

The encoder is written out longhand rather than delegating to ``json.dumps`` so the
escaping table is visible and portable: the TypeScript and Rust cores use the same
table, line for line.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

__all__ = [
    "CanonicalError",
    "canonical_json",
    "canonical_bytes",
    "payload_digest",
    "parse_json",
    "MAX_SAFE_INT",
    "MIN_SAFE_INT",
]

MAX_SAFE_INT = 9007199254740991  # 2**53 - 1
MIN_SAFE_INT = -9007199254740991


class CanonicalError(ValueError):
    """Value cannot be represented as canonical JSON."""


_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _encode_string(value: str) -> str:
    out = ['"']
    for ch in value:
        escaped = _ESCAPES.get(ch)
        if escaped is not None:
            out.append(escaped)
        elif ch < "\x20":
            out.append("\\u%04x" % ord(ch))
        elif "\ud800" <= ch <= "\udfff":
            raise CanonicalError("lone surrogate in string")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _encode(value: Any, out: list, depth: int) -> None:
    if depth > 100:
        raise CanonicalError("value nested too deeply")

    if value is None:
        out.append("null")
        return

    # bool must precede int: bool is a subclass of int in Python.
    if value is True:
        out.append("true")
        return
    if value is False:
        out.append("false")
        return

    if isinstance(value, int):
        if not (MIN_SAFE_INT <= value <= MAX_SAFE_INT):
            raise CanonicalError(f"integer {value} outside safe range")
        out.append(str(value))
        return

    if isinstance(value, float):
        raise CanonicalError(
            "floating-point numbers are not permitted in wire v1; "
            "use a scaled integer or a string"
        )

    if isinstance(value, str):
        out.append(_encode_string(value))
        return

    if isinstance(value, Mapping):
        keys = list(value.keys())
        for key in keys:
            if not isinstance(key, str):
                raise CanonicalError("object keys must be strings")
        out.append("{")
        first = True
        for key in sorted(keys):
            if not first:
                out.append(",")
            first = False
            out.append(_encode_string(key))
            out.append(":")
            _encode(value[key], out, depth + 1)
        out.append("}")
        return

    if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
        out.append("[")
        first = True
        for item in value:
            if not first:
                out.append(",")
            first = False
            _encode(item, out, depth + 1)
        out.append("]")
        return

    raise CanonicalError(f"type {type(value).__name__} is not JSON representable")


def canonical_json(value: Any) -> str:
    """Serialize ``value`` to canonical JSON text."""
    out: list = []
    _encode(value, out, 0)
    return "".join(out)


def canonical_bytes(value: Any) -> bytes:
    """Serialize ``value`` to canonical JSON, UTF-8 encoded."""
    return canonical_json(value).encode("utf-8")


def payload_digest(data: Any) -> str:
    """Payload digest — SPEC/wire-v1.md section 2."""
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


def _reject_duplicate_keys(pairs):
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise CanonicalError(f"duplicate object key: {key!r}")
        seen.add(key)
    return dict(pairs)


def parse_json(text: str) -> Any:
    """Parse JSON text, rejecting duplicate object keys and non-finite numbers."""
    try:
        return json.loads(
            text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_bad_constant
        )
    except CanonicalError:
        raise
    except json.JSONDecodeError as exc:
        raise CanonicalError(f"invalid JSON: {exc}") from exc


def _bad_constant(name: str):
    raise CanonicalError(f"{name} is not valid JSON")
