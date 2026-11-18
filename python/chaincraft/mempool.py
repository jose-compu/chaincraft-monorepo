"""Transaction pool — SPEC/features/mempool-basic.md."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .object import merkle_digest

__all__ = [
    "DEFAULT_CAPACITY",
    "DEFAULT_MIN_FEE",
    "DEFAULT_TTL_MS",
    "DEFAULT_MAX_PER_SENDER",
    "DEFAULT_RBF_MIN_INCREASE",
    "Mempool",
    "transaction_id",
]

DEFAULT_CAPACITY = 8
DEFAULT_MIN_FEE = 0
DEFAULT_TTL_MS = 60_000
DEFAULT_MAX_PER_SENDER = 0
DEFAULT_RBF_MIN_INCREASE = 1


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def transaction_id(fee: int, nonce: int, payload: str, sender: str) -> str:
    return merkle_digest(
        {"fee": fee, "nonce": nonce, "payload": payload, "sender": sender}
    )


def parse_tx(message: Any) -> Optional[Tuple[str, str, int, int, str]]:
    if not isinstance(message, dict):
        return None
    sender = message.get("sender")
    payload = message.get("payload")
    fee = message.get("fee")
    nonce = message.get("nonce")
    if not isinstance(sender, str) or not sender:
        return None
    if not isinstance(payload, str) or not payload:
        return None
    if not _is_int(fee) or fee < 0:
        return None
    if not _is_int(nonce) or nonce < 0:
        return None
    return transaction_id(fee, nonce, payload, sender), sender, fee, nonce, payload


class Mempool:
    def __init__(
        self,
        capacity: int = DEFAULT_CAPACITY,
        min_fee: int = DEFAULT_MIN_FEE,
        ttl_ms: int = DEFAULT_TTL_MS,
        max_per_sender: int = DEFAULT_MAX_PER_SENDER,
        rbf_min_increase: int = DEFAULT_RBF_MIN_INCREASE,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if min_fee < 0:
            raise ValueError("min_fee must be >= 0")
        if ttl_ms < 0:
            raise ValueError("ttl_ms must be >= 0")
        if max_per_sender < 0:
            raise ValueError("max_per_sender must be >= 0")
        if rbf_min_increase < 1:
            raise ValueError("rbf_min_increase must be >= 1")
        self.capacity = capacity
        self.min_fee = min_fee
        self.ttl_ms = ttl_ms
        self.max_per_sender = max_per_sender
        self.rbf_min_increase = rbf_min_increase
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._slots: Dict[Tuple[str, int], str] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def ids(self) -> List[str]:
        return list(self._entries)

    def insert(self, message: Any, now_ms: int) -> Dict[str, Any]:
        expired = self.sweep(now_ms)
        parsed = parse_tx(message)
        if parsed is None:
            return self._result(False, "", "", expired)
        txid, sender, fee, nonce, _payload = parsed
        if txid in self._entries:
            return self._result(False, "", "", expired)
        if fee < self.min_fee:
            return self._result(False, "", "", expired)
        replaced = ""
        slot = (sender, nonce)
        existing_id = self._slots.get(slot)
        if existing_id is not None:
            existing = self._entries[existing_id]
            if fee < existing["fee"] + self.rbf_min_increase:
                return self._result(False, "", "", expired)
            self._discard(existing_id)
            replaced = existing_id
        if replaced == "" and self.max_per_sender > 0:
            if self._sender_count(sender) >= self.max_per_sender:
                return self._result(False, "", "", expired)
        evicted = ""
        if len(self._entries) >= self.capacity:
            victim = self._lowest_fee()
            if victim is None or self._entries[victim]["fee"] >= fee:
                return self._result(False, replaced, "", expired)
            self._discard(victim)
            evicted = victim
        self._entries[txid] = {
            "fee": fee,
            "nonce": nonce,
            "payload": message["payload"],
            "received_at": now_ms,
            "sender": sender,
        }
        self._slots[slot] = txid
        return self._result(True, replaced, evicted, expired)

    def remove(self, txid: str) -> bool:
        return self._discard(txid)

    def sweep(self, now_ms: int) -> int:
        if self.ttl_ms == 0:
            return 0
        expired = [
            txid
            for txid, entry in self._entries.items()
            if now_ms - entry["received_at"] > self.ttl_ms
        ]
        for txid in expired:
            self._discard(txid)
        return len(expired)

    def _result(
        self, accepted: bool, replaced: str, evicted: str, expired: int
    ) -> Dict[str, Any]:
        return {
            "accepted": accepted,
            "evicted": evicted,
            "expired": expired,
            "replaced": replaced,
        }

    def _discard(self, txid: str) -> bool:
        entry = self._entries.pop(txid, None)
        if entry is None:
            return False
        self._slots.pop((entry["sender"], entry["nonce"]), None)
        return True

    def _sender_count(self, sender: str) -> int:
        return sum(1 for entry in self._entries.values() if entry["sender"] == sender)

    def _lowest_fee(self) -> Optional[str]:
        if not self._entries:
            return None
        best_id = None
        best_fee = None
        for txid, entry in self._entries.items():
            if best_fee is None or entry["fee"] < best_fee:
                best_id = txid
                best_fee = entry["fee"]
        return best_id
