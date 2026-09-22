"""Channel adapters — SPEC/features/channel-adapters.md.

UDP has a localhost datagram socket. Mail, WebRTC, and forum are in-memory
buses. ctl.hello.listen is not touched here.
"""

from __future__ import annotations

import re
import socket
from typing import Dict, List, Tuple

from .channel import parse_address
from .framing import MAX_UDP_BYTES, decode_datagram

__all__ = [
    "MAX_UDP_PAYLOAD",
    "MAX_MAIL_BYTES",
    "MAX_WEBRTC_BYTES",
    "MAX_FORUM_BYTES",
    "AdapterBus",
    "AdapterChannel",
    "UdpLink",
    "udp_bus",
    "mail_bus",
    "webrtc_bus",
    "forum_bus",
]

MAX_UDP_PAYLOAD = MAX_UDP_BYTES
MAX_MAIL_BYTES = 4096
MAX_WEBRTC_BYTES = MAX_UDP_BYTES
MAX_FORUM_BYTES = 4096
_HEX = re.compile(r"^[0-9a-f]+$")


def udp_bus() -> "AdapterBus":
    return AdapterBus("udp", MAX_UDP_PAYLOAD)


def mail_bus() -> "AdapterBus":
    return AdapterBus("mailto", MAX_MAIL_BYTES)


def webrtc_bus() -> "AdapterBus":
    return AdapterBus("webrtc", MAX_WEBRTC_BYTES)


def forum_bus() -> "AdapterBus":
    return AdapterBus("forum", MAX_FORUM_BYTES)


class AdapterBus:
    def __init__(self, scheme: str, max_bytes: int) -> None:
        self.scheme = scheme
        self.max_bytes = max_bytes
        self._bound: Dict[str, "AdapterChannel"] = {}


class AdapterChannel:
    def __init__(self, bus: AdapterBus) -> None:
        self._bus = bus
        self.listen_addr = ""
        self._inbox: List[Dict[str, str]] = []

    def listen(self, addr: str) -> bool:
        parsed = parse_address(addr)
        if not parsed["ok"] or parsed["scheme"] != self._bus.scheme or self.listen_addr:
            return False
        name = parsed["canonical"]
        if name in self._bus._bound:
            return False
        self.listen_addr = name
        self._bus._bound[name] = self
        return True

    def dial(self, addr: str) -> bool:
        parsed = parse_address(addr)
        if not parsed["ok"] or parsed["scheme"] != self._bus.scheme:
            return False
        return parsed["canonical"] in self._bus._bound

    def send(self, addr: str, data: str) -> bool:
        parsed = parse_address(addr)
        if (
            not parsed["ok"]
            or parsed["scheme"] != self._bus.scheme
            or not _valid_payload(data, self._bus.max_bytes)
        ):
            return False
        dest = self._bus._bound.get(parsed["canonical"])
        if dest is None:
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


def _valid_payload(data: str, max_bytes: int) -> bool:
    if not isinstance(data, str) or len(data) < 2 or len(data) % 2 != 0:
        return False
    if _HEX.fullmatch(data) is None:
        return False
    return 1 <= len(data) // 2 <= max_bytes


class UdpLink:
    """One localhost datagram socket. Not advertised as ctl.hello.listen."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.settimeout(2)

    @property
    def host_port(self) -> str:
        host, port = self._sock.getsockname()
        return f"{host}:{port}"

    def send(self, host_port: str, body: bytes) -> None:
        decode_datagram(body)
        host, port_s = host_port.rsplit(":", 1)
        self._sock.sendto(body, (host, int(port_s)))

    def recv(self) -> Tuple[str, bytes]:
        data, addr = self._sock.recvfrom(MAX_UDP_BYTES)
        body = decode_datagram(data)
        return f"{addr[0]}:{addr[1]}", body

    def close(self) -> None:
        self._sock.close()
