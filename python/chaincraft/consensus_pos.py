"""Proof-of-stake object — SPEC/features/consensus-pos.md."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = ["DEFAULT_SEED", "DEFAULT_VALIDATORS", "ProofOfStake", "proposer_for"]

DEFAULT_SEED = "chaincraft-pos-v1"
DEFAULT_VALIDATORS = {"alice": 2, "bob": 1, "carol": 1}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def proposer_for(slot: int, seed: str, validators: Mapping[str, int]) -> str:
    total = sum(validators.values())
    digest = merkle_digest({"seed": seed, "slot": slot})
    pick = int(digest, 16) % total
    acc = 0
    for vid in sorted(validators):
        acc += validators[vid]
        if pick < acc:
            return vid
    raise RuntimeError("stake walk missed")


class ProofOfStake(SharedObject):
    def __init__(
        self,
        seed: str = DEFAULT_SEED,
        validators: Optional[Mapping[str, int]] = None,
    ) -> None:
        if not seed:
            raise ValueError("seed must be a non-empty string")
        table = dict(validators) if validators is not None else dict(DEFAULT_VALIDATORS)
        if not table:
            raise ValueError("validators must not be empty")
        for vid, stake in table.items():
            if not vid or not _is_int(stake) or stake < 1:
                raise ValueError(
                    "each validator needs a non-empty id and positive stake"
                )
        self.seed = seed
        self.validators = table
        self.current = 0
        self.last_proposer = ""
        self.head = ""

    def proposer(self, slot: int) -> str:
        return proposer_for(slot, self.seed, self.validators)

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        parsed = self._parse(message)
        if parsed is None:
            return self.emit_state_memento()
        slot, proposer, payload = parsed
        self.current = slot
        self.last_proposer = proposer
        self.head = merkle_digest({"payload": payload, "slot": slot, "v": 1})
        return self.emit_state_memento()

    def emit_state_memento(self) -> StateMemento:
        return StateMemento.normalize(self.head, [])

    def get_state_digests(self) -> List[str]:
        return [self.head] if self.head else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        return {
            "head": self.head,
            "last_proposer": self.last_proposer,
            "slot": self.current,
        }

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("consensus") != "pos":
            return None
        slot = message.get("slot")
        proposer = message.get("proposer")
        payload = message.get("payload")
        if not _is_int(slot) or slot != self.current + 1:
            return None
        if not isinstance(proposer, str) or not proposer:
            return None
        if not isinstance(payload, str) or not payload:
            return None
        if proposer != self.proposer(slot):
            return None
        return slot, proposer, payload
