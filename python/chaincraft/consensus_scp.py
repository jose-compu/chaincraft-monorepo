"""Stellar SCP (FBA with quorum slices) — SPEC/features/consensus-scp.md."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = ["SCP"]

# Simple pedagogical model. Full SCP paper has more nuanced quorum
# intersection and federated voting. This focuses on the 4 phases + ballot.
PHASES = ("nominate", "prepare", "confirm", "externalize")


class SCP(SharedObject):
    """Pedagogical Stellar SCP object.

    Each instance represents one node's view. `slices` is list of trusted
    peer groups (including self). A message's `quorum` is accepted if it
    intersects a slice with majority support (simplified threshold).
    """

    def __init__(self, node: str = "n0", slices: Optional[List[List[str]]] = None) -> None:
        if not node or not isinstance(node, str):
            raise ValueError("node must be a non-empty string")
        if slices is None:
            slices = [[node]]  # default: trust only self
        if not isinstance(slices, list) or not slices:
            raise ValueError("slices must be a non-empty list of lists")
        for s in slices:
            if not isinstance(s, list) or not s or node not in s:
                raise ValueError("every slice must contain local node")
        self.node = node
        self.slices = [sorted(s) for s in slices]  # normalize
        self.phase = "nominate"
        self.ballot = {"counter": 0, "value": None}
        self.accepted = {}  # phase -> ballot
        self.votes = {}  # node -> ballot per phase

    def is_valid(self, message: Any) -> bool:
        """Return True only on valid parse + quorum slice intersection."""
        parsed = self._parse(message)
        if parsed is None:
            return False
        _, _, _, quorum = parsed
        return self._is_quorum_valid(quorum)

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        if not self.is_valid(message):
            return self.emit_state_memento()

        parsed = self._parse(message)
        assert parsed is not None
        phase, ballot, from_node, quorum = parsed

        # Update local view if ballot is higher or same phase progression
        if self._should_update(ballot, phase):
            self.ballot = ballot
            self.phase = phase
            self.accepted[phase] = ballot
            self.votes.setdefault(from_node, {})[phase] = ballot

        return self.emit_state_memento()

    def _parse(self, message: Any) -> Optional[Tuple[str, Dict, str, List[str]]]:
        """Return (phase, ballot, node, quorum) or None if invalid."""
        if not isinstance(message, dict):
            return None
        if message.get("consensus") != "scp":
            return None

        phase = message.get("phase")
        if phase not in PHASES:
            return None

        ballot = message.get("ballot")
        if not isinstance(ballot, dict) or "counter" not in ballot or "value" not in ballot:
            return None
        counter = ballot["counter"]
        if not isinstance(counter, int) or counter < 0:
            return None

        from_node = message.get("node")
        if not isinstance(from_node, str) or not from_node:
            return None

        quorum = message.get("quorum", [])
        if not isinstance(quorum, list) or not all(isinstance(n, str) for n in quorum):
            return None

        return phase, {"counter": counter, "value": ballot["value"]}, from_node, sorted(set(quorum))

    def _is_quorum_valid(self, quorum: List[str]) -> bool:
        """Simplified: does the quorum contain the local node and intersect
        at least one slice with majority (>50%) of its members?"""
        if self.node not in quorum:
            return False
        for s in self.slices:
            intersection = len(set(s) & set(quorum))
            if intersection * 2 > len(s):  # strict majority
                return True
        return False

    def _should_update(self, new_ballot: Dict, new_phase: str) -> bool:
        """Ballot counter must be >= current; phase must be valid progression."""
        if new_ballot["counter"] < self.ballot["counter"]:
            return False
        phase_order = {"nominate": 0, "prepare": 1, "confirm": 2, "externalize": 3}
        if phase_order.get(new_phase, -1) < phase_order.get(self.phase, -1):
            return False
        return True

    def emit_state_memento(self) -> StateMemento:
        return StateMemento.normalize(
            merkle_digest({"state": self.state(), "v": 1}),
            [],
        )

    def get_state_digests(self) -> List[str]:
        memo = self.emit_state_memento()
        return [memo.canonical_digest] if memo.canonical_digest else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        return {
            "node": self.node,
            "slices": self.slices,
            "phase": self.phase,
            "ballot": self.ballot,
            "accepted": self.accepted,
        }

    def __repr__(self) -> str:
        return f"SCP(node={self.node}, phase={self.phase}, ballot={self.ballot})"
