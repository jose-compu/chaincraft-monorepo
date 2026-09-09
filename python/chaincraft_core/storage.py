"""Persistent message store — SPEC/features/storage-persistent.md."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

__all__ = ["DEFAULT_CAPACITY", "MessageStore", "is_valid_id"]

DEFAULT_CAPACITY = 8
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def is_valid_id(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


class MessageStore:
    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._entries: Dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def ids(self) -> List[str]:
        return list(self._entries)

    def put(self, record_id: str, body: str) -> bool:
        if not is_valid_id(record_id) or not isinstance(body, str) or not body:
            return False
        if record_id in self._entries:
            self._entries[record_id] = body
            return False
        if len(self._entries) >= self.capacity:
            oldest = next(iter(self._entries))
            del self._entries[oldest]
        self._entries[record_id] = body
        return True

    def get(self, record_id: str) -> Dict[str, Any]:
        body = self._entries.get(record_id)
        if body is None:
            return {"body": "", "found": False}
        return {"body": body, "found": True}

    def remove(self, record_id: str) -> bool:
        if record_id not in self._entries:
            return False
        del self._entries[record_id]
        return True

    def dump(self) -> Dict[str, Any]:
        return {
            "entries": [{"body": body, "id": record_id} for record_id, body in self._entries.items()],
            "v": 1,
        }

    def load(self, snapshot: Any) -> bool:
        parsed = self._parse_snapshot(snapshot)
        if parsed is None:
            return False
        self._entries = parsed
        return True

    def _parse_snapshot(self, snapshot: Any) -> Optional[Dict[str, str]]:
        if not isinstance(snapshot, dict) or snapshot.get("v") != 1:
            return None
        raw = snapshot.get("entries")
        if not isinstance(raw, list) or len(raw) > self.capacity:
            return None
        out: Dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                return None
            record_id = item.get("id")
            body = item.get("body")
            if not is_valid_id(record_id) or not isinstance(body, str) or not body:
                return None
            if record_id in out:
                return None
            out[record_id] = body
        return out
