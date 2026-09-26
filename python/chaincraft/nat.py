"""Prototype NAT traversal — SPEC/features/discovery-nat.md."""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Tuple

from .discovery import is_valid_address
from .envelope import ProtocolError

__all__ = [
    "APP_NAT",
    "PUNCH_HEX",
    "NatTraversal",
    "binding_request",
    "binding_success",
    "parse_binding_response",
]

APP_NAT = "app.nat"
PUNCH_HEX = "00"
_MAGIC = 0x2112A442
_MAGIC_B = b"\x21\x12\xa4\x42"
_BINDING_REQUEST = 0x0001
_BINDING_SUCCESS = 0x0101
_XOR_MAPPED = 0x0020
_FAIL_PARSE: Dict[str, Any] = {"ok": False, "host": "", "port": 0}


def binding_request(txid: str) -> Dict[str, Any]:
    raw = _txid(txid)
    if raw is None:
        return {"ok": False, "packet": ""}
    return {"ok": True, "packet": (_header(_BINDING_REQUEST, 0, raw)).hex()}


def binding_success(txid: str, host: str, port: Any) -> Dict[str, Any]:
    raw = _txid(txid)
    if raw is None or _ipv4(host) is None or not _port(port):
        return {"ok": False, "packet": ""}
    value = _xor_mapped(host, port)
    attr = struct.pack(">HH", _XOR_MAPPED, len(value)) + value
    return {"ok": True, "packet": (_header(_BINDING_SUCCESS, len(attr), raw) + attr).hex()}


def parse_binding_response(packet: Any, txid: Any) -> Dict[str, Any]:
    raw = _unhex(packet)
    ident = _txid(txid)
    if raw is None or ident is None or len(raw) < 20:
        return dict(_FAIL_PARSE)
    msg_type, length, magic = struct.unpack(">HHI", raw[:8])
    if msg_type != _BINDING_SUCCESS or magic != _MAGIC or raw[8:20] != ident:
        return dict(_FAIL_PARSE)
    if length != len(raw) - 20:
        return dict(_FAIL_PARSE)
    offset = 20
    end = 20 + length
    found: Optional[bytes] = None
    while offset + 4 <= end:
        atype, alen = struct.unpack(">HH", raw[offset : offset + 4])
        offset += 4
        if offset + alen > end:
            return dict(_FAIL_PARSE)
        value = raw[offset : offset + alen]
        offset += alen
        pad = (4 - (alen % 4)) % 4
        if offset + pad > end:
            return dict(_FAIL_PARSE)
        offset += pad
        if atype == _XOR_MAPPED and found is None:
            found = value
    if offset != end or found is None or len(found) != 8 or found[0] != 0 or found[1] != 1:
        return dict(_FAIL_PARSE)
    port = struct.unpack(">H", found[2:4])[0] ^ 0x2112
    if not 1 <= port <= 65535:
        return dict(_FAIL_PARSE)
    host = ".".join(str(found[4 + i] ^ _MAGIC_B[i]) for i in range(4))
    return {"ok": True, "host": host, "port": port}


class NatTraversal:
    """STUN mapping, hole punch, and app.nat relay. No sockets."""

    def __init__(
        self,
        listen: str,
        external: Optional[str] = None,
        relay: Optional[str] = None,
    ) -> None:
        if not is_valid_address(listen):
            raise ProtocolError("invalid listen address")
        if external is not None and not is_valid_address(external):
            raise ProtocolError("invalid external address")
        if relay is not None and not is_valid_address(relay):
            raise ProtocolError("invalid relay address")
        self._listen = listen
        self._fixed = external
        self._mapped = external
        self._relay = relay
        self._armed = False
        self._opened: List[str] = []
        self._seen: List[Tuple[str, ...]] = []

    def armed(self) -> bool:
        return self._armed

    def arm(self, transport: str) -> bool:
        self._armed = transport == "udp"
        return self._armed

    def external_address(self) -> str:
        return self._mapped or ""

    def advertise(self) -> str:
        return self._mapped or self._listen

    def observe_stun(self, packet: Any, txid: Any) -> bool:
        if not self._armed or self._fixed is not None:
            return False
        parsed = parse_binding_response(packet, txid)
        if not parsed["ok"]:
            return False
        mapped = f"{parsed['host']}:{parsed['port']}"
        if not is_valid_address(mapped):
            return False
        self._mapped = mapped
        return True

    def punch(self, peer: Any) -> Dict[str, Any]:
        if not self._armed or not isinstance(peer, str) or not is_valid_address(peer) or self._ours(peer):
            return {"ok": False, "datagram": "", "addr": ""}
        return {"ok": True, "datagram": PUNCH_HEX, "addr": peer}

    def observe_punch(self, datagram: Any, origin: Any) -> bool:
        if not self._armed or datagram != PUNCH_HEX:
            return False
        if not isinstance(origin, str) or not is_valid_address(origin) or self._ours(origin):
            return False
        if origin not in self._opened:
            self._opened.append(origin)
        return True

    def opened(self) -> List[str]:
        return list(self._opened)

    def relay_request(self, target: Any) -> Dict[str, Any]:
        if (
            not self._armed
            or self._relay is None
            or not isinstance(target, str)
            or not is_valid_address(target)
            or self._ours(target)
            or target == self._relay
            or target in self._opened
        ):
            return {"ok": False, "message": None}
        return {
            "ok": True,
            "message": {
                "from": self.advertise(),
                "nat": "request",
                "relay": self._relay,
                "target": target,
            },
        }

    def handle(self, message: Any) -> Dict[str, Any]:
        fail: Dict[str, Any] = {"ok": False, "action": "", "addr": "", "reply": None}
        if not self._armed or not isinstance(message, dict):
            return fail
        kind = message.get("nat")
        origin = message.get("from")
        target = message.get("target")
        if kind not in ("request", "response"):
            return fail
        if not isinstance(origin, str) or not isinstance(target, str):
            return fail
        if not is_valid_address(origin) or not is_valid_address(target) or self._ours(origin):
            return fail
        if kind == "request":
            relay = message.get("relay")
            if not isinstance(relay, str) or not is_valid_address(relay):
                return fail
            ident: Tuple[str, ...] = ("request", origin, target, relay)
        else:
            relay = ""
            ident = ("response", origin, target)
        if ident in self._seen:
            return fail
        if target == self._listen or target == self.advertise():
            self._seen.append(ident)
            reply = None
            if kind == "request":
                reply = {"from": self.advertise(), "nat": "response", "target": origin}
            elif origin not in self._opened:
                self._opened.append(origin)
            return {"ok": True, "action": "punch", "addr": origin, "reply": reply}
        if kind == "request" and (relay == self._listen or relay == self.advertise()):
            self._seen.append(ident)
            return {
                "ok": True,
                "action": "forward",
                "addr": target,
                "reply": {
                    "from": origin,
                    "nat": "request",
                    "relay": relay,
                    "target": target,
                },
            }
        return fail

    def _ours(self, addr: str) -> bool:
        return addr == self._listen or addr == self.advertise()


def _header(msg_type: int, length: int, txid: bytes) -> bytes:
    return struct.pack(">HHI", msg_type, length, _MAGIC) + txid


def _xor_mapped(host: str, port: int) -> bytes:
    octets = _ipv4(host)
    assert octets is not None
    xport = port ^ 0x2112
    addr = bytes(octets[i] ^ _MAGIC_B[i] for i in range(4))
    return struct.pack(">BBH", 0, 1, xport) + addr


def _txid(value: Any) -> Optional[bytes]:
    raw = _unhex(value)
    if raw is None or len(raw) != 12:
        return None
    return raw


def _unhex(value: Any) -> Optional[bytes]:
    if not isinstance(value, str) or len(value) % 2:
        return None
    if any(ch not in "0123456789abcdef" for ch in value):
        return None
    return bytes.fromhex(value)


def _port(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535


def _ipv4(host: Any) -> Optional[List[int]]:
    if not isinstance(host, str):
        return None
    labels = host.split(".")
    if len(labels) != 4:
        return None
    octets: List[int] = []
    for label in labels:
        if not label or not all("0" <= ch <= "9" for ch in label) or (len(label) > 1 and label.startswith("0")):
            return None
        octet = int(label)
        if octet > 255:
            return None
        octets.append(octet)
    return octets
