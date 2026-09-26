"""PBFT object — SPEC/features/consensus-pbft.md."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = ["DEFAULT_REPLICAS", "PHASES", "PBFT"]

DEFAULT_REPLICAS = ("r0", "r1", "r2", "r3")
PHASES = ("pre-prepare", "prepare", "commit")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


class PBFT(SharedObject):
    def __init__(self, replicas: Optional[Sequence[str]] = None) -> None:
        names = list(replicas) if replicas is not None else list(DEFAULT_REPLICAS)
        if not names or len(set(names)) != len(names) or any(not n for n in names):
            raise ValueError("replicas must be unique non-empty ids")
        self.replicas = sorted(names)
        self.n = len(self.replicas)
        self.f = (self.n - 1) // 3
        self.quorum = 2 * self.f + 1
        self.view = 0
        self.sequence = 1
        self._digest: str = ""
        self._prepares: Dict[str, str] = {}
        self._commits: Dict[str, str] = {}
        self.executed: List[Dict[str, Any]] = []

    def primary_for(self, view: int) -> str:
        return self.replicas[view % self.n]

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        parsed = self._parse(message)
        if parsed is None:
            return self.emit_state_memento()
        phase, view, sequence, digest, replica = parsed
        if view != self.view or sequence != self.sequence:
            return self.emit_state_memento()
        if phase == "pre-prepare":
            if not self._digest:
                self._digest = digest
        elif not self._digest or digest != self._digest:
            return self.emit_state_memento()
        elif phase == "prepare":
            self._prepares.setdefault(replica, digest)
        else:
            self._commits.setdefault(replica, digest)
        if (
            self._digest
            and self._count(self._prepares) >= self.quorum
            and self._count(self._commits) >= self.quorum
        ):
            self.executed.append({"digest": self._digest, "seq": self.sequence})
            self.sequence += 1
            self._digest = ""
            self._prepares = {}
            self._commits = {}
        return self.emit_state_memento()

    def emit_state_memento(self) -> StateMemento:
        return StateMemento.normalize(
            merkle_digest(
                {
                    "executed": [item["digest"] for item in self.executed],
                    "sequence": self.sequence,
                    "v": 1,
                }
            ),
            [],
        )

    def get_state_digests(self) -> List[str]:
        head = self.emit_state_memento().canonical_digest
        return [head] if head else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        return {
            "commits": self._count(self._commits),
            "executed": list(self.executed),
            "prepares": self._count(self._prepares),
            "sequence": self.sequence,
            "view": self.view,
        }

    def _count(self, votes: Dict[str, str]) -> int:
        return sum(1 for digest in votes.values() if digest == self._digest)

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("consensus") != "pbft":
            return None
        phase = message.get("phase")
        view = message.get("view")
        sequence = message.get("sequence")
        digest = message.get("digest")
        replica = message.get("replica")
        if phase not in PHASES:
            return None
        if not _is_int(view) or view < 0:
            return None
        if not _is_int(sequence) or sequence < 1:
            return None
        if not isinstance(digest, str) or not _HEX64.match(digest):
            return None
        if not isinstance(replica, str) or replica not in self.replicas:
            return None
        if phase == "pre-prepare":
            value = message.get("value")
            if not isinstance(value, str):
                return None
            if digest != merkle_digest(value):
                return None
            if replica != self.primary_for(view):
                return None
        return phase, view, sequence, digest, replica
