"""PeerJS ids, broker options, and an in-memory cross-scheme relay.

SPEC/features/channel-peer.md. Signaling is an HTTP GET. The relay does not
open an ICE data channel.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .channel import is_peer_id, parse_address
from .envelope import Envelope, ProtocolError

__all__ = [
    "DEFAULT_PEER_ORIGIN",
    "PEER_KEY",
    "EnvelopeRelay",
    "fetch_peer_id",
    "is_peer_id",
    "parse_peer_id_body",
    "peer_options",
]

DEFAULT_PEER_ORIGIN = "https://dechess-org-peerjs.vercel.app"
PEER_KEY = "peerjs"
_RELAY = frozenset({"udp", "mailto", "webrtc", "forum", "pipe"})


def parse_peer_id_body(text: Any) -> Optional[str]:
    if not isinstance(text, str):
        return None
    ident = text.strip()
    if not is_peer_id(ident):
        return None
    return ident


def peer_options(origin: str = DEFAULT_PEER_ORIGIN) -> Dict[str, Any]:
    parsed = urlparse(origin)
    secure = parsed.scheme == "https"
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("peer origin must be http or https")
    port = parsed.port if parsed.port is not None else (443 if secure else 80)
    return {
        "host": parsed.hostname,
        "port": port,
        "path": "/",
        "secure": secure,
        "key": PEER_KEY,
    }


def fetch_peer_id(origin: str = DEFAULT_PEER_ORIGIN, timeout: float = 10.0) -> str:
    url = origin.rstrip("/") + "/peerjs/id"
    request = Request(url, headers={"Accept": "text/plain"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    ident = parse_peer_id_body(body)
    if ident is None:
        raise ValueError("invalid peer id")
    return ident


class EnvelopeRelay:
    """Deliver one envelope id from a joined address to every other member."""

    def __init__(self) -> None:
        self._order: List[str] = []
        self._inbox: Dict[str, List[Dict[str, str]]] = {}
        self._seen: set[str] = set()

    def join(self, addr: str) -> bool:
        parsed = parse_address(addr)
        if not parsed["ok"] or parsed["scheme"] not in _RELAY:
            return False
        canonical = parsed["canonical"]
        if canonical in self._inbox:
            return False
        self._order.append(canonical)
        self._inbox[canonical] = []
        return True

    def publish(self, src: str, type_name: str, data: Any) -> Optional[str]:
        parsed = parse_address(src)
        if not parsed["ok"]:
            return None
        canonical = parsed["canonical"]
        if canonical not in self._inbox:
            return None
        try:
            env = Envelope.build(type_name, data, ts=0)
        except ProtocolError:
            return None
        if env.id in self._seen:
            return env.id
        self._seen.add(env.id)
        item = {"id": env.id, "type": env.type, "from": canonical}
        for member in self._order:
            if member == canonical:
                continue
            self._inbox[member].append(dict(item))
        return env.id

    def take(self, addr: str) -> List[Dict[str, str]]:
        parsed = parse_address(addr)
        if not parsed["ok"]:
            return []
        box = self._inbox.get(parsed["canonical"])
        if box is None:
            return []
        out = list(box)
        box.clear()
        return out
