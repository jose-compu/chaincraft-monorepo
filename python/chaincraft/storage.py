"""Persistent message store — SPEC/features/storage-persistent.md, storage-index.md."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .canonical import MAX_SAFE_INT, MIN_SAFE_INT
from .envelope import Envelope, ProtocolError

__all__ = ["DEFAULT_CAPACITY", "MessageStore", "is_valid_id"]

DEFAULT_CAPACITY = 8
_MAX_REGISTRATIONS = 8
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TYPE_RE = re.compile(r"^[a-z0-9._-]{1,64}$")
_FIELD_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

IndexKey = Tuple[str, str, str, Any]
RegKey = Tuple[str, str]


def is_valid_id(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def _is_wire_int(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and MIN_SAFE_INT <= value <= MAX_SAFE_INT
    )


def _index_values(raw: Any) -> List[Any]:
    if isinstance(raw, str):
        return [raw]
    if _is_wire_int(raw):
        return [raw]
    if isinstance(raw, bool):
        return [raw]
    if isinstance(raw, list):
        out: List[Any] = []
        seen: Set[Any] = set()
        for item in raw:
            if isinstance(item, str) or _is_wire_int(item) or isinstance(item, bool):
                if item not in seen:
                    seen.add(item)
                    out.append(item)
        return out
    return []


def _value_tag(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return "s"
    if isinstance(value, bool):
        return "b"
    if _is_wire_int(value):
        return "i"
    return None


class MessageStore:
    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._entries: Dict[str, str] = {}
        self._registrations: Set[RegKey] = set()
        self._postings: Dict[IndexKey, List[str]] = {}
        self._id_keys: Dict[str, Set[IndexKey]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def ids(self) -> List[str]:
        return list(self._entries)

    def register(self, type_: str, field: str) -> bool:
        if not isinstance(type_, str) or not _TYPE_RE.match(type_):
            return False
        if not isinstance(field, str) or not _FIELD_RE.match(field):
            return False
        key = (type_, field)
        if key in self._registrations:
            return True
        if len(self._registrations) >= _MAX_REGISTRATIONS:
            return False
        self._registrations.add(key)
        return True

    def query(self, type_: str, field: str, value: Any) -> List[str]:
        tag = _value_tag(value)
        if tag is None:
            return []
        key: IndexKey = (type_, field, tag, value)
        if (type_, field) not in self._registrations:
            return []
        return list(self._postings.get(key, []))

    def put(self, record_id: str, body: str) -> bool:
        if not is_valid_id(record_id) or not isinstance(body, str) or not body:
            return False
        if record_id in self._entries:
            self._unindex_id(record_id)
            self._entries[record_id] = body
            self._index_body(record_id, body)
            return False
        if len(self._entries) >= self.capacity:
            oldest = next(iter(self._entries))
            self._unindex_id(oldest)
            del self._entries[oldest]
        self._entries[record_id] = body
        self._index_body(record_id, body)
        return True

    def get(self, record_id: str) -> Dict[str, Any]:
        body = self._entries.get(record_id)
        if body is None:
            return {"body": "", "found": False}
        return {"body": body, "found": True}

    def remove(self, record_id: str) -> bool:
        if record_id not in self._entries:
            return False
        self._unindex_id(record_id)
        del self._entries[record_id]
        return True

    def dump(self) -> Dict[str, Any]:
        return {
            "entries": [
                {"body": body, "id": record_id}
                for record_id, body in self._entries.items()
            ],
            "v": 1,
        }

    def load(self, snapshot: Any) -> bool:
        parsed = self._parse_snapshot(snapshot)
        if parsed is None:
            return False
        self._entries = parsed
        self._rebuild_index()
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

    def _rebuild_index(self) -> None:
        self._postings.clear()
        self._id_keys.clear()
        for record_id, body in self._entries.items():
            self._index_body(record_id, body)

    def _unindex_id(self, record_id: str) -> None:
        keys = self._id_keys.pop(record_id, set())
        for key in keys:
            bucket = self._postings.get(key)
            if not bucket:
                continue
            if record_id in bucket:
                bucket.remove(record_id)
            if not bucket:
                del self._postings[key]

    def _index_body(self, record_id: str, body: str) -> None:
        try:
            env = Envelope.parse(body)
        except ProtocolError:
            return
        if not isinstance(env.data, dict):
            return
        keys_for_id: Set[IndexKey] = set()
        for type_, field in self._registrations:
            if env.type != type_:
                continue
            if field not in env.data:
                continue
            for value in _index_values(env.data[field]):
                tag = _value_tag(value)
                if tag is None:
                    continue
                idx: IndexKey = (type_, field, tag, value)
                keys_for_id.add(idx)
                bucket = self._postings.setdefault(idx, [])
                if record_id not in bucket:
                    bucket.append(record_id)
        if keys_for_id:
            self._id_keys[record_id] = keys_for_id
