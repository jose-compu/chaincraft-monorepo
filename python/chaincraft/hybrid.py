"""One mesh, one channel per peer — SPEC/features/channel-hybrid.md.

Gossip is relayed to every other member that can hold the envelope.
``link.*`` and ``ctl.*`` are delivered to one member. ``ctl.hello.listen``
is not stored here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .channel import parse_address
from .envelope import Envelope, ProtocolError

__all__ = ["HOP_CAP", "LinkMesh", "hello_caps"]

HOP_CAP = {
    "tcp": 262144,
    "udp": 65507,
    "webrtc": 65507,
    "pipe": 65507,
    "mailto": 4096,
    "forum": 4096,
    "loop": 64,
}


def hello_caps(udp: bool) -> List[str]:
    caps = ["digest-sync", "gossip"]
    if udp:
        caps.append("udp")
    return sorted(caps)


class LinkMesh:
    def __init__(self) -> None:
        self._order: List[str] = []
        self._scheme: Dict[str, str] = {}
        self._inbox: Dict[str, List[Dict[str, str]]] = {}
        self._seen: set[str] = set()

    def join(self, addr: str) -> bool:
        parsed = parse_address(addr)
        if not parsed["ok"] or parsed["scheme"] not in HOP_CAP:
            return False
        canonical = parsed["canonical"]
        if canonical in self._inbox:
            return False
        self._order.append(canonical)
        self._scheme[canonical] = parsed["scheme"]
        self._inbox[canonical] = []
        return True

    def gossip(self, src: str, type_name: str, data: Any) -> Optional[str]:
        return self._send(src, None, type_name, data, gossip=True)

    def direct(self, src: str, dst: str, type_name: str, data: Any) -> Optional[str]:
        return self._send(src, dst, type_name, data, gossip=False)

    def take(self, addr: str) -> List[Dict[str, str]]:
        canonical = self._canonical(addr)
        if canonical is None:
            return []
        box = self._inbox.get(canonical)
        if box is None:
            return []
        out = list(box)
        box.clear()
        return out

    def _send(
        self,
        src: str,
        dst: Optional[str],
        type_name: str,
        data: Any,
        *,
        gossip: bool,
    ) -> Optional[str]:
        source = self._canonical(src)
        if source is None or source not in self._inbox:
            return None
        target = None
        if not gossip:
            target = self._canonical(dst or "")
            if target is None or target not in self._inbox:
                return None
        try:
            env = Envelope.build(type_name, data, ts=0)
        except ProtocolError:
            return None
        if gossip and env.is_control():
            return None
        if not gossip and not env.is_control():
            return None
        if env.id in self._seen:
            return env.id
        self._seen.add(env.id)
        size = len(env.to_bytes())
        item = {"id": env.id, "type": env.type, "from": source}
        if gossip:
            for member in self._order:
                if member == source:
                    continue
                if size <= HOP_CAP[self._scheme[member]]:
                    self._inbox[member].append(dict(item))
        elif target is not None and size <= HOP_CAP[self._scheme[target]]:
            self._inbox[target].append(dict(item))
        return env.id

    @staticmethod
    def _canonical(addr: str) -> Optional[str]:
        parsed = parse_address(addr)
        if not parsed["ok"]:
            return None
        return parsed["canonical"]
