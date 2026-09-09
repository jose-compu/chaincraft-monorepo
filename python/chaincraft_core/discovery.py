"""Peer address book and local-discovery policy.

SPEC/features/discovery-peer.md and SPEC/features/discovery-local.md.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set

__all__ = [
    "DEFAULT_CAPACITY",
    "DEFAULT_TIMEOUT_MS",
    "is_valid_address",
    "is_connect_allowed",
    "is_resolved_ip_allowed",
    "AddressBook",
    "LocalDiscovery",
]

DEFAULT_CAPACITY = 50
DEFAULT_TIMEOUT_MS = 120_000


def is_resolved_ip_allowed(ip: str) -> bool:
    labels = ip.split(".")
    if len(labels) != 4 or not all(label.isdigit() for label in labels):
        return False
    a, b = int(labels[0]), int(labels[1])
    if a == 127:
        return True
    if a == 10:
        return True
    if a == 192 and b == 168:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    return False


def is_connect_allowed(address: str) -> bool:
    if not is_valid_address(address):
        return False
    host, _port = address.rsplit(":", 1)
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".local"):
        return True
    return is_resolved_ip_allowed(host)


def is_valid_address(address: str) -> bool:
    if not isinstance(address, str) or ":" not in address:
        return False
    host, port = address.rsplit(":", 1)
    return _valid_host(host) and _valid_port(port)


def _valid_port(port: str) -> bool:
    if not port.isdigit():
        return False
    if len(port) > 1 and port[0] == "0":
        return False
    value = int(port)
    return 1 <= value <= 65535


def _valid_host(host: str) -> bool:
    if not host or len(host) > 253:
        return False
    labels = host.split(".")
    if len(labels) == 4 and all(label.isdigit() for label in labels):
        return _valid_ipv4(labels)
    return _valid_hostname(labels)


def _valid_ipv4(labels: List[str]) -> bool:
    for label in labels:
        if len(label) > 1 and label[0] == "0":
            return False
        if not (0 <= int(label) <= 255):
            return False
    return True


def _valid_hostname(labels: List[str]) -> bool:
    if not labels or labels[0] == "" or labels[-1] == "":
        return False
    for label in labels:
        if not (1 <= len(label) <= 63):
            return False
        if label[0] == "-" or label[-1] == "-":
            return False
        if not all(ch.isalnum() or ch == "-" for ch in label):
            return False
    return True


class AddressBook:
    """Bounded, insertion-ordered peer store — discovery-peer.md."""

    __slots__ = ("listen", "capacity", "timeout_ms", "_entries", "_solicited")

    def __init__(
        self,
        listen: Optional[str] = None,
        capacity: int = DEFAULT_CAPACITY,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be a positive integer")
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be a positive integer")
        if listen is not None and not is_valid_address(listen):
            raise ValueError("listen must be a valid address or None")
        self.listen = listen
        self.capacity = capacity
        self.timeout_ms = timeout_ms
        self._entries: Dict[str, int] = {}
        self._solicited: Set[str] = set()

    def __contains__(self, address: object) -> bool:
        return address in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def addresses(self) -> List[str]:
        return list(self._entries)

    def last_seen(self, address: str) -> Optional[int]:
        return self._entries.get(address)

    def insert(self, address: str, now_ms: int) -> bool:
        return self._put(address, now_ms, evict=True)

    def ingest(self, addresses: Iterable[str], now_ms: int, solicited: bool) -> int:
        if not solicited:
            return 0
        added = 0
        for address in addresses:
            if self._put(address, now_ms, evict=False):
                added += 1
        return added

    def advertise(self) -> List[str]:
        return sorted(self._entries)

    def sweep(self, now_ms: int) -> int:
        expired = [
            address
            for address, seen in self._entries.items()
            if now_ms - seen > self.timeout_ms
        ]
        for address in expired:
            del self._entries[address]
            self._solicited.discard(address)
        return len(expired)

    def mark_solicited(self, peer: str) -> bool:
        if not is_valid_address(peer):
            return False
        self._solicited.add(peer)
        return True

    def is_solicited(self, peer: str) -> bool:
        return peer in self._solicited

    def clear_solicited(self, peer: str) -> None:
        self._solicited.discard(peer)

    def _put(self, address: str, now_ms: int, evict: bool) -> bool:
        if not is_valid_address(address) or address == self.listen:
            return False
        if address in self._entries:
            self._entries[address] = now_ms
            return False
        if len(self._entries) >= self.capacity:
            if not evict:
                return False
            oldest = next(iter(self._entries))
            del self._entries[oldest]
            self._solicited.discard(oldest)
        self._entries[address] = now_ms
        return True


class LocalDiscovery:
    """Local peer-list policy — discovery-local.md."""

    __slots__ = ("book", "enabled")

    def __init__(self, book: AddressBook, enabled: bool = True) -> None:
        self.book = book
        self.enabled = enabled

    def request(self, peer: str) -> bool:
        if not self.enabled:
            return False
        return self.book.mark_solicited(peer)

    def reply(self) -> Optional[List[str]]:
        if not self.enabled:
            return None
        return self.book.advertise()

    def accept(self, from_peer: str, addresses: Iterable[str], now_ms: int) -> int:
        if not self.enabled or not self.book.is_solicited(from_peer):
            return 0
        self.book.clear_solicited(from_peer)
        return self.book.ingest(addresses, now_ms, True)
