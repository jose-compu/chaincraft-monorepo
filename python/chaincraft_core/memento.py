"""StateMemento — SPEC/semantics-v1.md section 4."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

__all__ = ["StateMemento"]


@dataclass(frozen=True)
class StateMemento:
    """A snapshot of an object's state, threaded through the apply pipeline."""

    canonical_digest: str = ""
    frontier_digests: List[str] = field(default_factory=list)
    revision: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def normalize(
        cls,
        canonical_digest: str = "",
        frontier_digests: Optional[Sequence[str]] = None,
    ) -> "StateMemento":
        """Build a normalized memento — semantics-v1.md section 4.1.

        The frontier is sorted and deduplicated so two nodes reaching the same
        set of heads by different routes produce the same memento.
        """
        heads: Iterable[str] = frontier_digests or ()
        collected = {head for head in heads if head}
        if canonical_digest:
            collected.add(canonical_digest)
        return cls(
            canonical_digest=canonical_digest,
            frontier_digests=sorted(collected),
            revision=0,
            metadata={},
        )

    def indicates_reorg_against(self, previous: Optional["StateMemento"]) -> bool:
        """Whether the head moved to a branch not building on ``previous``.

        See semantics-v1.md section 4.2. All four conditions must hold.
        """
        if previous is None:
            return False
        if not self.canonical_digest or not previous.canonical_digest:
            return False
        if self.canonical_digest == previous.canonical_digest:
            return False
        return previous.canonical_digest not in self.frontier_digests

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_digest": self.canonical_digest,
            "frontier_digests": list(self.frontier_digests),
            "revision": self.revision,
            "metadata": dict(self.metadata),
        }
