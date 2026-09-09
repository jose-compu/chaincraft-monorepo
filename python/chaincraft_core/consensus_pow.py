"""Proof-of-work object — SPEC/features/consensus-pow.md."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = ["DEFAULT_DIFFICULTY", "ProofOfWork", "block_id", "meets_work"]

DEFAULT_DIFFICULTY = 2


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def block_id(height: int, miner: str, nonce: int, parent: str, payload: str) -> str:
    return merkle_digest(
        {
            "height": height,
            "miner": miner,
            "nonce": nonce,
            "parent": parent,
            "payload": payload,
        }
    )


def meets_work(digest: str, difficulty: int) -> bool:
    return len(digest) >= difficulty and digest[:difficulty] == "0" * difficulty


def mine(parent: str, height: int, miner: str, payload: str, difficulty: int) -> Dict[str, Any]:
    nonce = 0
    while True:
        digest = block_id(height, miner, nonce, parent, payload)
        if meets_work(digest, difficulty):
            return {
                "consensus": "pow",
                "height": height,
                "miner": miner,
                "nonce": nonce,
                "parent": parent,
                "payload": payload,
                "id": digest,
            }
        nonce += 1


class ProofOfWork(SharedObject):
    def __init__(self, difficulty: int = DEFAULT_DIFFICULTY) -> None:
        if not (1 <= difficulty <= 64):
            raise ValueError("difficulty must be in 1..64")
        self.difficulty = difficulty
        self._blocks: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []

    def is_valid(self, message: Any) -> bool:
        parsed = self._parse(message)
        return parsed is not None

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
        return {"blocks": list(self._order), "height": height, "tip": tip}

    def _tip(self) -> tuple:
        if not self._blocks:
            return "", 0
        best = None
        best_height = -1
        for digest, record in self._blocks.items():
            height = record["height"]
            if height > best_height or (height == best_height and digest < best):
                best = digest
                best_height = height
        return best, best_height

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("consensus") != "pow":
            return None
        height = message.get("height")
        nonce = message.get("nonce")
        miner = message.get("miner")
        parent = message.get("parent")
        payload = message.get("payload")
        if not _is_int(height) or height < 1:
            return None
        if not _is_int(nonce) or nonce < 0:
            return None
        if not isinstance(miner, str) or not miner:
            return None
        if not isinstance(parent, str):
            return None
        if not isinstance(payload, str) or not payload:
            return None
        if parent == "":
            if height != 1:
                return None
        else:
            prior = self._blocks.get(parent)
            if prior is None or height != prior["height"] + 1:
                return None
        digest = block_id(height, miner, nonce, parent, payload)
        if not meets_work(digest, self.difficulty) or digest in self._blocks:
            return None
        return digest, {
            "height": height,
            "miner": miner,
            "nonce": nonce,
            "parent": parent,
            "payload": payload,
        }
