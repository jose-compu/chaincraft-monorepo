"""Proof-of-elapsed-time object — SPEC/features/consensus-poet.md."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import vdf
from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = ["ProofOfElapsedTime", "ticket_id"]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def _canonical_proof_hex(text: str) -> Optional[str]:
    if not isinstance(text, str):
        return None
    try:
        proof_int = vdf.hex_to_proof(text)
    except ValueError:
        return None
    canonical = vdf.proof_to_hex(proof_int)
    if canonical != text:
        return None
    return text


def ticket_id(author: str, payload: str, proof: str, wait: int) -> str:
    return merkle_digest(
        {
            "author": author,
            "payload": payload,
            "proof": proof,
            "wait": wait,
        }
    )


class ProofOfElapsedTime(SharedObject):
    def __init__(self, seed: str) -> None:
        if not isinstance(seed, str) or not seed:
            raise ValueError("seed must be a non-empty string")
        self._seed = seed
        self._seed_bytes = seed.encode("utf-8")
        self._tickets: Dict[str, Dict[str, Any]] = {}
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
        self._tickets[digest] = record
        self._order.append(digest)
        return self.emit_state_memento()

    def emit_state_memento(self) -> StateMemento:
        winner, wait = self._winner()
        return StateMemento.normalize(
            merkle_digest({"v": 1, "wait": wait, "winner": winner}),
            [],
        )

    def get_state_digests(self) -> List[str]:
        winner, _ = self._winner()
        return [winner] if winner else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        winner, wait = self._winner()
        canonical = [winner] if winner else []
        return {
            "canonical": canonical,
            "tickets": list(self._order),
            "wait": wait,
            "winner": winner,
        }

    def _winner(self) -> tuple[str, int]:
        if not self._tickets:
            return "", 0
        best = ""
        best_wait = 2**32
        for digest, record in self._tickets.items():
            wait = record["wait"]
            if wait < best_wait or (wait == best_wait and digest < best):
                best = digest
                best_wait = wait
        return best, best_wait

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("consensus") != "poet":
            return None
        wait = message.get("wait")
        author = message.get("author")
        payload = message.get("payload")
        proof = message.get("proof")
        if not _is_int(wait) or wait < 1 or wait > 4_294_967_295:
            return None
        if not isinstance(author, str) or not author:
            return None
        if not isinstance(payload, str) or not payload:
            return None
        proof_hex = _canonical_proof_hex(proof)
        if proof_hex is None:
            return None
        proof_int = vdf.hex_to_proof(proof_hex)
        if not vdf.verify(self._seed_bytes, wait, proof_int):
            return None
        digest = ticket_id(author, payload, proof_hex, wait)
        if digest in self._tickets:
            return None
        return digest, {
            "author": author,
            "payload": payload,
            "proof": proof_hex,
            "wait": wait,
        }
