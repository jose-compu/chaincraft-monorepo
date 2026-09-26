"""Conformance fixture objects — SPEC/semantics-v1.md section 8.

These exist only so replay vectors are portable: every implementation feeds
pipeline.json through objects behaving exactly like these. They are not part of
the shipped API, which is why they live under tests/ rather than in the package.

Reimplementing these in Rust and TypeScript is part of porting `object.pipeline`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from chaincraft import ObjectRegistry, SharedObject, StateMemento, merkle_digest

__all__ = ["Counter", "Mirror", "build_registry", "snapshot"]


def _is_int(value: Any) -> bool:
    """Integers only. bool is a subclass of int in Python and must not pass."""
    return isinstance(value, int) and value is not True and value is not False


class Counter(SharedObject):
    """Merkelized, chain-shaped — semantics-v1.md section 8.1."""

    def __init__(self) -> None:
        self.seq = 0
        self.total = 0
        self.head = ""

    def is_valid(self, message: Any) -> bool:
        if not isinstance(message, dict):
            return False
        delta = message.get("delta")
        seq = message.get("seq")
        if not _is_int(delta) or not _is_int(seq):
            return False
        if not -100 <= delta <= 100:
            return False
        return seq == self.seq + 1

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        previous = self.head
        self.total += message["delta"]
        self.seq = message["seq"]
        self.head = merkle_digest(
            {
                "previous_digest": previous,
                "seq": self.seq,
                "total": self.total,
                "v": 1,
            }
        )
        inherited = frontier_state.frontier_digests if frontier_state else []
        return StateMemento.normalize(self.head, inherited)

    def emit_state_memento(self) -> StateMemento:
        return StateMemento.normalize(self.head, [])

    def get_state_digests(self) -> List[str]:
        return [self.head] if self.head else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        return {"seq": self.seq, "total": self.total, "head": self.head}


class Mirror(SharedObject):
    """Records what the pipeline threaded into it — semantics-v1.md section 8.2.

    Returns nothing from add_message, which exercises the emit_state_memento()
    branch of the threading rule in section 3 step 4.
    """

    def __init__(self) -> None:
        self.count = 0
        self.last_frontier: List[str] = []

    def is_valid(self, message: Any) -> bool:
        if isinstance(message, dict) and message.get("reject_mirror") is True:
            return False
        return True

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        self.count += 1
        self.last_frontier = (
            list(frontier_state.frontier_digests) if frontier_state else []
        )
        return None

    def emit_state_memento(self) -> StateMemento:
        return StateMemento.normalize("", self.last_frontier)

    def get_state_digests(self) -> List[str]:
        return []

    def is_merkelized(self) -> bool:
        return False

    def state(self) -> Dict[str, Any]:
        return {"count": self.count, "last_frontier": list(self.last_frontier)}


def build_registry() -> ObjectRegistry:
    """Registration order is counter then mirror — section 8.3."""
    registry = ObjectRegistry()
    registry.register("counter", Counter())
    registry.register("mirror", Mirror())
    return registry


def snapshot(registry: ObjectRegistry) -> Dict[str, Any]:
    """Observable state, in the shape recorded by replay vectors — section 8.4."""
    return {
        "counter": registry.get("counter").state(),
        "mirror": registry.get("mirror").state(),
    }
