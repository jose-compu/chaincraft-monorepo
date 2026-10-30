"""Last-write-wins key-value CRDT — SPEC/features/protocol-crdt-kv.md."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from .canonical import MAX_SAFE_INT
from .object import SharedObject

__all__ = ["MAX_KEYS", "MAX_VALUE", "CrdtKv"]

MAX_KEYS = 32
MAX_VALUE = 256
_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def _name(value: Any) -> bool:
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


class CrdtKv(SharedObject):
    def __init__(self) -> None:
        self._keys: Dict[str, Tuple[int, str, str, bool]] = {}

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def receive(self, message: Any) -> None:
        parsed = self._parse(message)
        if parsed is None:
            return
        key, ts, writer, value, deleted = parsed
        current = self._keys.get(key)
        if current is None:
            self._keys[key] = (ts, writer, value, deleted)
            return
        stored_ts, stored_writer, _, _ = current
        if ts == stored_ts and writer == stored_writer:
            return
        if ts > stored_ts or (ts == stored_ts and writer < stored_writer):
            self._keys[key] = (ts, writer, value, deleted)

    def state(self) -> Dict[str, Any]:
        keys = []
        for key in sorted(self._keys):
            ts, writer, value, deleted = self._keys[key]
            keys.append(
                {
                    "deleted": deleted,
                    "key": key,
                    "ts": ts,
                    "value": value,
                    "writer": writer,
                }
            )
        return {"keys": keys}

    def _parse(self, message: Any) -> Optional[Tuple[str, int, str, str, bool]]:
        if not isinstance(message, dict) or message.get("app") != "crdt":
            return None
        op = message.get("op")
        key = message.get("key")
        writer = message.get("writer")
        ts = message.get("ts")
        if op not in ("set", "del"):
            return None
        if not _name(key) or not _name(writer):
            return None
        if not _is_int(ts) or not (0 <= ts <= MAX_SAFE_INT):
            return None
        deleted = op == "del"
        if deleted:
            value = ""
        else:
            value = message.get("value")
            if not isinstance(value, str) or not (1 <= len(value) <= MAX_VALUE):
                return None
        current = self._keys.get(key)
        if current is None:
            if len(self._keys) >= MAX_KEYS:
                return None
            return (key, ts, writer, value, deleted)
        stored_ts, stored_writer, stored_value, stored_deleted = current
        if ts == stored_ts and writer == stored_writer:
            if deleted != stored_deleted or value != stored_value:
                return None
            return (key, ts, writer, value, deleted)
        return (key, ts, writer, value, deleted)
