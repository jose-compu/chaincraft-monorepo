"""Node JSON-lines command surface — SPEC/features/cli-node.md."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .canonical import CanonicalError, parse_json, payload_digest
from .channel import parse_address

__all__ = ["NodeSession"]

_TYPE_RE = re.compile(r"^[a-z0-9._-]{1,64}$")


class NodeSession:
    def __init__(self, impl: str, listen: str) -> None:
        if not impl or not listen:
            raise ValueError("impl and listen must be non-empty")
        self.impl = impl
        self.listen = listen
        self.peers: List[str] = []
        self.ids: List[str] = []
        self.closed = False

    def start(self) -> List[Dict[str, Any]]:
        return [{"event": "ready", "addr": self.listen, "impl": self.impl}]

    def handle(self, line: str) -> List[Dict[str, Any]]:
        if not line.strip():
            return []
        if self.closed:
            return [self._error("closed")]
        try:
            command = parse_json(line)
        except CanonicalError:
            return [self._error("invalid json")]
        if not isinstance(command, dict):
            return [self._error("invalid json")]
        name = command.get("cmd")
        if name == "connect":
            return self._connect(command)
        if name == "send":
            return self._send(command)
        if name == "ids":
            return [{"event": "ids", "ids": list(self.ids)}]
        if name == "quit":
            self.closed = True
            return [{"event": "quit"}]
        return [self._error("unknown cmd")]

    def state(self) -> Dict[str, Any]:
        return {"closed": self.closed, "ids": list(self.ids), "peers": list(self.peers)}

    def _connect(self, command: Dict[str, Any]) -> List[Dict[str, Any]]:
        addr = command.get("addr")
        if not isinstance(addr, str) or not parse_address(addr)["ok"]:
            return [self._error("invalid address")]
        if addr not in self.peers:
            self.peers.append(addr)
        return [{"event": "connected", "addr": addr}]

    def _send(self, command: Dict[str, Any]) -> List[Dict[str, Any]]:
        type_name = command.get("type")
        if not isinstance(type_name, str) or not _TYPE_RE.match(type_name):
            return [self._error("invalid send")]
        if "data" not in command:
            return [self._error("invalid send")]
        try:
            digest = payload_digest(command["data"])
        except CanonicalError:
            return [self._error("invalid send")]
        self.ids.append(digest)
        return [{"event": "sent", "id": digest}]

    @staticmethod
    def _error(message: str) -> Dict[str, Any]:
        return {"event": "error", "message": message}
