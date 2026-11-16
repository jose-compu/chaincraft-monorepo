"""Proof-of-authority object — SPEC/features/consensus-poa.md."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = ["ProofOfAuthority", "block_id", "proposer_for"]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def proposer_for(height: int, authorities: Sequence[str]) -> str:
    return authorities[(height - 1) % len(authorities)]


def block_id(height: int, parent: str, payload: str, proposer: str) -> str:
    return merkle_digest(
        {
            "height": height,
            "parent": parent,
            "payload": payload,
            "proposer": proposer,
        }
    )


class ProofOfAuthority(SharedObject):
    def __init__(self, authorities: Sequence[str]) -> None:
        if not authorities:
            raise ValueError("authorities must be non-empty")
        seen: set[str] = set()
        ordered: List[str] = []
        for authority in authorities:
            if not isinstance(authority, str) or not authority:
                raise ValueError("each authority must be a non-empty string")
            if authority in seen:
                raise ValueError("authorities must be distinct")
            seen.add(authority)
            ordered.append(authority)
        self.authorities = ordered
        self._blocks: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        parsed = self._parse(message)
        if parsed is None:
            return self.emit_state_memento()
        digest, record = parsed
        self._blocks[digest] = record
        self._order.append(digest)
        return self.emit_state_memento()

    def emit_state_memento(self) -> StateMemento:
        tip, height = self._tip()
        return StateMemento.normalize(
            merkle_digest({"height": height, "tip": tip, "v": 1}),
            [],
        )

    def get_state_digests(self) -> List[str]:
        tip, _ = self._tip()
        return [tip] if tip else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        tip, height = self._tip()
        return {
            "blocks": list(self._order),
            "canonical": self._canonical(tip),
            "height": height,
            "tip": tip,
        }

    def _tip(self) -> tuple:
        if not self._blocks:
            return "", 0
        best = ""
        best_height = -1
        for digest, record in self._blocks.items():
            height = record["height"]
            if height > best_height or (
                height == best_height and (not best or digest < best)
            ):
                best = digest
                best_height = height
        return best, best_height

    def _canonical(self, tip: str) -> List[str]:
        chain: List[str] = []
        cursor = tip
        while cursor:
            chain.append(cursor)
            cursor = self._blocks[cursor]["parent"]
        chain.reverse()
        return chain

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("consensus") != "poa":
            return None
        height = message.get("height")
        proposer = message.get("proposer")
        parent = message.get("parent")
        payload = message.get("payload")
        if not _is_int(height) or height < 1:
            return None
        if not isinstance(proposer, str) or not proposer:
            return None
        if not isinstance(parent, str):
            return None
        if not isinstance(payload, str) or not payload:
            return None
        if proposer != proposer_for(height, self.authorities):
            return None
        if parent == "":
            if height != 1:
                return None
        else:
            prior = self._blocks.get(parent)
            if prior is None or height != prior["height"] + 1:
                return None
        digest = block_id(height, parent, payload, proposer)
        if digest in self._blocks:
            return None
        return digest, {
            "height": height,
            "parent": parent,
            "payload": payload,
            "proposer": proposer,
        }
