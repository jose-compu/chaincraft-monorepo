"""UTXO ledger — SPEC/features/ledger-utxo.md."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .canonical import MAX_SAFE_INT
from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = ["DEFAULT_ALLOCATIONS", "UtxoLedger", "transaction_id"]

DEFAULT_ALLOCATIONS: Dict[str, int] = {"alice": 100}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def _normalize_allocations(allocations: Mapping[str, int]) -> Dict[str, int]:
    if not allocations:
        raise ValueError("allocations must not be empty")
    out: Dict[str, int] = {}
    for owner in sorted(allocations):
        value = allocations[owner]
        if not owner:
            raise ValueError("owner id must be non-empty")
        if not _is_int(value) or not (1 <= value <= MAX_SAFE_INT):
            raise ValueError("each allocation must be an integer in 1..2^53-1")
        out[owner] = value
    return out


def transaction_id(fee: int, inputs: List[str], outputs: List[Dict[str, Any]]) -> str:
    return merkle_digest({"fee": fee, "inputs": inputs, "outputs": outputs})


class UtxoLedger(SharedObject):
    def __init__(self, allocations: Optional[Mapping[str, int]] = None) -> None:
        genesis = _normalize_allocations(allocations or DEFAULT_ALLOCATIONS)
        self._utxos: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        for owner, value in genesis.items():
            utxo_id = f"genesis:{owner}"
            self._utxos[utxo_id] = {"owner": owner, "value": value}
            self._order.append(utxo_id)
        self._burned = 0

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        parsed = self._parse(message)
        if parsed is None:
            return self.emit_state_memento()
        fee, inputs, outputs, txid = parsed
        for utxo_id in inputs:
            del self._utxos[utxo_id]
            self._order.remove(utxo_id)
        for index, output in enumerate(outputs):
            out_id = f"{txid}:{index}"
            self._utxos[out_id] = {"owner": output["owner"], "value": output["value"]}
            self._order.append(out_id)
        self._burned += fee
        return self.emit_state_memento()

    def emit_state_memento(self) -> StateMemento:
        return StateMemento.normalize(
            merkle_digest({"burned": self._burned, "utxos": self._entries(), "v": 1}),
            [],
        )

    def get_state_digests(self) -> list:
        digest = self.emit_state_memento().canonical_digest
        return [digest] if digest else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        entries = self._entries()
        return {
            "burned": self._burned,
            "supply": sum(item["value"] for item in entries),
            "utxos": entries,
        }

    def _entries(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": utxo_id,
                "owner": self._utxos[utxo_id]["owner"],
                "value": self._utxos[utxo_id]["value"],
            }
            for utxo_id in self._order
        ]

    def _parse(
        self, message: Any
    ) -> Optional[Tuple[int, List[str], List[Dict[str, Any]], str]]:
        if not isinstance(message, dict) or message.get("ledger") != "utxo":
            return None
        fee = message.get("fee")
        raw_inputs = message.get("inputs")
        raw_outputs = message.get("outputs")
        if not _is_int(fee) or fee < 0:
            return None
        if not isinstance(raw_inputs, list) or not raw_inputs:
            return None
        inputs: List[str] = []
        seen = set()
        incoming = 0
        for item in raw_inputs:
            if not isinstance(item, str) or not item or item in seen:
                return None
            record = self._utxos.get(item)
            if record is None:
                return None
            seen.add(item)
            inputs.append(item)
            incoming += record["value"]
        if not isinstance(raw_outputs, list):
            return None
        outputs: List[Dict[str, Any]] = []
        outgoing = 0
        for item in raw_outputs:
            if not isinstance(item, dict):
                return None
            owner = item.get("owner")
            value = item.get("value")
            if not isinstance(owner, str) or not owner:
                return None
            if not _is_int(value) or value < 1:
                return None
            outgoing += value
            outputs.append({"owner": owner, "value": value})
        if incoming != outgoing + fee:
            return None
        txid = transaction_id(fee, inputs, outputs)
        return fee, inputs, outputs, txid
