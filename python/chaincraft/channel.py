"""Address URIs and an in-process loop channel — SPEC/features/wire-channel.md."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .discovery import is_connect_allowed as host_port_connect_allowed
from .discovery import is_valid_address

__all__ = [
    "MAX_LOOP_BYTES",
    "parse_address",
    "is_connect_allowed",
    "is_peer_id",
    "LoopBus",
    "LoopChannel",
]

MAX_LOOP_BYTES = 64
_HEX = re.compile(r"^[0-9a-f]+$")
_PEER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LOCAL = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
_THREAD = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_FAIL: Dict[str, Any] = {"ok": False, "scheme": "", "canonical": "", "cap": ""}
_AUTHORITY = ("tcp", "udp")
_COLON = ("mailto", "webrtc", "forum", "loop", "pipe")


def parse_address(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, str) or not raw:
        return dict(_FAIL)
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        if scheme not in _AUTHORITY:
            return dict(_FAIL)
        if any(ch in rest for ch in "@/?#"):
            return dict(_FAIL)
        if not is_valid_address(rest):
            return dict(_FAIL)
        return _ok(scheme, f"{scheme}://{rest}")
    for scheme in _COLON:
        prefix = f"{scheme}:"
        if raw.startswith(prefix):
            return _parse_colon(scheme, raw[len(prefix) :])
    if is_valid_address(raw):
        return _ok("tcp", f"tcp://{raw}")
    return dict(_FAIL)


def is_peer_id(value: Any) -> bool:
    return isinstance(value, str) and _PEER_ID.fullmatch(value) is not None


def is_connect_allowed(raw: str) -> bool:
    parsed = parse_address(raw)
    if not parsed["ok"]:
        return False
    if parsed["scheme"] in _AUTHORITY:
        rest = parsed["canonical"].split("://", 1)[1]
        return host_port_connect_allowed(rest)
    return True


def _ok(scheme: str, canonical: str) -> Dict[str, Any]:
    return {"ok": True, "scheme": scheme, "canonical": canonical, "cap": scheme}


def _parse_colon(scheme: str, rest: str) -> Dict[str, Any]:
    if scheme == "mailto":
        if rest.count("@") != 1:
            return dict(_FAIL)
        local, domain = rest.split("@", 1)
        if _LOCAL.fullmatch(local) is None or not is_valid_address(f"{domain}:1"):
            return dict(_FAIL)
        return _ok(scheme, f"mailto:{rest}")
    if scheme == "webrtc":
        if not is_peer_id(rest):
            return dict(_FAIL)
        return _ok(scheme, f"webrtc:{rest}")
    if scheme == "forum":
        if rest.count(":") != 1:
            return dict(_FAIL)
        profile, thread = rest.split(":", 1)
        if _LABEL.fullmatch(profile) is None or _THREAD.fullmatch(thread) is None:
            return dict(_FAIL)
        return _ok(scheme, f"forum:{rest}")
    if scheme in ("loop", "pipe"):
        if _LABEL.fullmatch(rest) is None:
            return dict(_FAIL)
        return _ok(scheme, f"{scheme}:{rest}")
    return dict(_FAIL)


def _valid_payload(data: str) -> bool:
    if not isinstance(data, str) or len(data) < 2 or len(data) % 2 != 0:
        return False
    if _HEX.fullmatch(data) is None:
        return False
    return 1 <= len(data) // 2 <= MAX_LOOP_BYTES


class LoopBus:
    def __init__(self) -> None:
        self._bound: Dict[str, "LoopChannel"] = {}


class LoopChannel:
    def __init__(self, bus: LoopBus) -> None:
        self._bus = bus
        self.listen_addr = ""
        self._inbox: List[Dict[str, str]] = []

    def listen(self, addr: str) -> bool:
        parsed = parse_address(addr)
        if not parsed["ok"] or parsed["scheme"] != "loop":
            return False
        if self.listen_addr:
            return False
        name = parsed["canonical"]
        if name in self._bus._bound:
            return False
        self.listen_addr = name
        self._bus._bound[name] = self
        return True

    def dial(self, addr: str) -> bool:
        parsed = parse_address(addr)
        if not parsed["ok"] or parsed["scheme"] != "loop":
            return False
        return parsed["canonical"] in self._bus._bound

    def send(self, addr: str, data: str) -> bool:
        parsed = parse_address(addr)
        if not parsed["ok"] or parsed["scheme"] != "loop":
            return False
        dest = self._bus._bound.get(parsed["canonical"])
        if dest is None or not _valid_payload(data):
            return False
        dest._inbox.append({"data": data, "from": self.listen_addr})
        return True

    def recv(self) -> List[Dict[str, str]]:
        out = self._inbox
        self._inbox = []
        return out

    def inbox(self) -> List[Dict[str, str]]:
        return list(self._inbox)

    def close(self) -> None:
        if self.listen_addr:
            current = self._bus._bound.get(self.listen_addr)
            if current is self:
                del self._bus._bound[self.listen_addr]
            self.listen_addr = ""
        self._inbox = []
