"""Shared object contract and digest helpers — SPEC/semantics-v1.md sections 2, 5, 6."""

from __future__ import annotations

import hashlib
from typing import Any, List, Optional, Sequence

from .canonical import canonical_bytes
from .memento import StateMemento

__all__ = [
    "SharedObject",
    "merkle_digest",
    "frontier_digest",
    "wins_replacement",
    "FRONTIER_FORMAT_VERSION",
]

FRONTIER_FORMAT_VERSION = 1


def merkle_digest(state_payload: Any) -> str:
    """Merkelized object digest — semantics-v1.md section 5.

    Deliberately the same canonicalization as the wire payload digest. Using a
    second canonicalization for state hashing is the mistake this shares code to
    avoid.
    """
    return hashlib.sha256(canonical_bytes(state_payload)).hexdigest()


def frontier_digest(heads: Sequence[str]) -> str:
    """Digest over a multi-head frontier — semantics-v1.md section 5.1."""
    payload = {
        "frontier_heads": sorted(head for head in heads if head),
        "v": FRONTIER_FORMAT_VERSION,
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def wins_replacement(
    candidate_rank: int,
    candidate_digest: str,
    incumbent_rank: int,
    incumbent_digest: str,
) -> bool:
    """Whether a candidate entry replaces the incumbent — section 6.1.

    An identical entry does not replace itself. Gossip redelivers the same
    message by design, so returning True on an exact match would let repeated
    delivery mutate state.
    """
    if candidate_rank > incumbent_rank:
        return True
    if candidate_rank < incumbent_rank:
        return False
    return candidate_digest < incumbent_digest


class SharedObject:
    """The application object contract — semantics-v1.md section 2.

    Called ``SharedObject`` in Python and ``ApplicationObject`` in Rust. The
    names differ; the contract does not.

    A prototype overrides ``receive`` only. Consensus objects override
    ``add_message`` and the snapshot.
    """

    def is_valid(self, message: Any) -> bool:
        """Whether ``message`` is an acceptable transition.

        MUST be deterministic and side-effect free. The pipeline calls this on
        every object before any object mutates, so a mutation here breaks the
        all-or-nothing guarantee in section 3. The default accepts.
        """
        return True

    def receive(self, message: Any) -> None:
        """Apply ``message`` locally. The default does nothing."""
        return None

    def add_message(
        self, message: Any, _frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        """Apply ``message``. The default calls ``receive`` and returns nothing.

        Override this only to read the frontier or to return a memento.
        """
        self.receive(message)
        return None

    def emit_state_memento(self) -> StateMemento:
        """Empty snapshot. Objects that sync override this."""
        return StateMemento.normalize()

    def get_state_digests(self) -> List[str]:
        """Frontier digests for multi-head structures. Empty by default."""
        return []

    def is_merkelized(self) -> bool:
        """Whether canonical digests are meaningful for this object."""
        return False
