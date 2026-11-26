"""Ouroboros slot-leader object — SPEC/features/consensus-ouroboros.md."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import vrf
from .canonical import MAX_SAFE_INT, canonical_json
from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = [
    "Ouroboros",
    "block_id",
    "eligible",
    "epoch_of",
]

_NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
_THRESHOLD = 1 << 256


def _is_int(value: Any) -> bool:
    return (
        isinstance(value, int)
        and value is not True
        and value is not False
        and 0 <= value <= MAX_SAFE_INT
    )


def epoch_of(slot: int, epoch_length: int) -> int:
    return (slot - 1) // epoch_length


def eligible(output: bytes, stake: int, total: int) -> bool:
    if total == stake:
        return True
    o_val = int.from_bytes(output, "big")
    return o_val * total < stake * _THRESHOLD


def block_id(
    slot: int,
    parent: str,
    payload: str,
    leader: str,
    pk: str,
    proof: str,
    output: str,
) -> str:
    return merkle_digest(
        {
            "leader": leader,
            "output": output,
            "parent": parent,
            "payload": payload,
            "pk": pk,
            "proof": proof,
            "slot": slot,
        }
    )


def _hex_lower(text: Any, nbytes: int) -> str | None:
    if not isinstance(text, str) or len(text) != nbytes * 2:
        return None
    if text != text.lower():
        return None
    try:
        bytes.fromhex(text)
    except ValueError:
        return None
    return text


class Ouroboros(SharedObject):
    def __init__(
        self,
        nonce: str,
        epoch_length: int,
        stakeholders: Sequence[Tuple[str, int, str]],
    ) -> None:
        if not isinstance(nonce, str) or not _NONCE_RE.match(nonce):
            raise ValueError("nonce must be 64 lowercase hex characters")
        if not _is_int(epoch_length) or epoch_length < 1:
            raise ValueError("epoch_length must be an integer >= 1")
        if not stakeholders:
            raise ValueError("stakeholders must be non-empty")
        seen: set[str] = set()
        table: Dict[str, Dict[str, Any]] = {}
        total = 0
        for sid, stake, pk_hex in stakeholders:
            if not isinstance(sid, str) or not sid:
                raise ValueError("each stakeholder id must be a non-empty string")
            if not _is_int(stake) or stake < 1:
                raise ValueError("each stake must be an integer >= 1")
            pk = _hex_lower(pk_hex, 33)
            if pk is None:
                raise ValueError("each pk must be 66 lowercase hex characters")
            if sid in seen:
                raise ValueError("stakeholder ids must be distinct")
            seen.add(sid)
            total += stake
            if total > MAX_SAFE_INT:
                raise ValueError("stake sum exceeds safe integer range")
            table[sid] = {"stake": stake, "pk": pk}
        self.nonce = nonce
        self.epoch_length = epoch_length
        self._stakeholders = table
        self._total_stake = total
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
        slot, tip = self._tip()
        _, nonce = self._next_slot_context(slot, tip)
        return StateMemento.normalize(
            merkle_digest({"nonce": nonce, "slot": slot, "tip": tip, "v": 1}),
            [],
        )

    def get_state_digests(self) -> List[str]:
        tip, _ = self._tip()
        return [tip] if tip else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        tip_slot, tip = self._tip()
        epoch, nonce = self._next_slot_context(tip_slot, tip)
        return {
            "slot": tip_slot,
            "tip": tip,
            "canonical": self._canonical(tip),
            "blocks": list(self._order),
            "epoch": epoch,
            "nonce": nonce,
        }

    def _tip(self) -> Tuple[int, str]:
        if not self._blocks:
            return 0, ""
        best = ""
        best_slot = -1
        for digest, record in self._blocks.items():
            slot = record["slot"]
            if slot > best_slot or (slot == best_slot and (not best or digest < best)):
                best = digest
                best_slot = slot
        return best_slot, best

    def _canonical(self, tip: str) -> List[str]:
        chain: List[str] = []
        cursor = tip
        while cursor:
            chain.append(cursor)
            cursor = self._blocks[cursor]["parent"]
        chain.reverse()
        return chain

    def _next_slot_context(self, tip_slot: int, tip: str) -> Tuple[int, str]:
        if tip_slot == 0:
            return epoch_of(1, self.epoch_length), self.nonce
        next_slot = tip_slot + 1
        return self._epoch_nonce_for_slot(next_slot, self._blocks[tip])

    def _epoch_nonce_for_slot(
        self, slot: int, parent: Optional[Dict[str, Any]]
    ) -> Tuple[int, str]:
        epoch = epoch_of(slot, self.epoch_length)
        pos = (slot - 1) % self.epoch_length
        if epoch == 0:
            return epoch, self.nonce
        if pos == 0:
            if parent is None:
                raise RuntimeError("parent required for epoch boundary")
            return epoch, parent["output"]
        if parent is None:
            raise RuntimeError("parent required")
        return epoch, parent["epoch_nonce"]

    def _vrf_message(self, epoch: int, nonce: str, slot: int, leader: str) -> bytes:
        return canonical_json(
            {"epoch": epoch, "nonce": nonce, "slot": slot, "stakeholder": leader}
        ).encode("utf-8")

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("consensus") != "ouroboros":
            return None
        slot = message.get("slot")
        leader = message.get("leader")
        parent = message.get("parent")
        payload = message.get("payload")
        pk = _hex_lower(message.get("pk"), 33)
        proof = _hex_lower(message.get("proof"), 64)
        output_hex = _hex_lower(message.get("output"), 32)
        if not _is_int(slot) or slot < 1:
            return None
        if not isinstance(leader, str) or not leader:
            return None
        if not isinstance(parent, str):
            return None
        if not isinstance(payload, str) or not payload:
            return None
        if pk is None or proof is None or output_hex is None:
            return None
        holder = self._stakeholders.get(leader)
        if holder is None or holder["pk"] != pk:
            return None
        if parent == "":
            if slot != 1:
                return None
            parent_record = None
        else:
            parent_record = self._blocks.get(parent)
            if parent_record is None or parent_record["slot"] != slot - 1:
                return None
        epoch, epoch_nonce = self._epoch_nonce_for_slot(slot, parent_record)
        vrf_msg = self._vrf_message(epoch, epoch_nonce, slot, leader)
        if not vrf.verify(
            vrf_msg,
            bytes.fromhex(proof),
            bytes.fromhex(pk),
            bytes.fromhex(output_hex),
        ):
            return None
        if not eligible(bytes.fromhex(output_hex), holder["stake"], self._total_stake):
            return None
        digest = block_id(slot, parent, payload, leader, pk, proof, output_hex)
        if digest in self._blocks:
            return None
        pos = (slot - 1) % self.epoch_length
        if epoch == 0:
            stored_nonce = self.nonce
        elif pos == 0:
            stored_nonce = parent_record["output"]  # type: ignore[union-attr]
        else:
            stored_nonce = parent_record["epoch_nonce"]  # type: ignore[union-attr]
        return digest, {
            "slot": slot,
            "parent": parent,
            "payload": payload,
            "leader": leader,
            "output": output_hex,
            "epoch_nonce": stored_nonce,
        }
