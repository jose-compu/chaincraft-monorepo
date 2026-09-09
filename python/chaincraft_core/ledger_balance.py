"""Account-balance ledger — SPEC/features/ledger-balance.md."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .canonical import MAX_SAFE_INT
from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = ["DEFAULT_ALLOCATIONS", "BalanceLedger"]

DEFAULT_ALLOCATIONS: Dict[str, int] = {"alice": 100}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def _normalize_allocations(allocations: Mapping[str, int]) -> Dict[str, int]:
    if not allocations:
        raise ValueError("allocations must not be empty")
    out: Dict[str, int] = {}
    for account in sorted(allocations):
        amount = allocations[account]
        if not account:
            raise ValueError("account id must be non-empty")
        if not _is_int(amount) or not (1 <= amount <= MAX_SAFE_INT):
            raise ValueError("each allocation must be an integer in 1..2^53-1")
        out[account] = amount
    return out


class BalanceLedger(SharedObject):
    def __init__(self, allocations: Optional[Mapping[str, int]] = None) -> None:
        self._balances = _normalize_allocations(allocations or DEFAULT_ALLOCATIONS)
        self._nonces = {account: 0 for account in self._balances}
        self._burned = 0

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        parsed = self._parse(message)
        if parsed is None:
            return self.emit_state_memento()
        sender, recipient, amount, fee = parsed
        self._balances[sender] = self._balances.get(sender, 0) - amount - fee
        self._balances[recipient] = self._balances.get(recipient, 0) + amount
        if recipient not in self._nonces:
            self._nonces[recipient] = 0
        self._nonces[sender] = self._nonces.get(sender, 0) + 1
        self._burned += fee
        return self.emit_state_memento()

    def emit_state_memento(self) -> StateMemento:
        return StateMemento.normalize(
            merkle_digest(
                {
                    "balances": dict(self._balances),
                    "burned": self._burned,
                    "nonces": dict(self._nonces),
                    "v": 1,
                }
            ),
            [],
        )

    def get_state_digests(self) -> list:
        digest = self.emit_state_memento().canonical_digest
        return [digest] if digest else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        return {
            "balances": dict(self._balances),
            "burned": self._burned,
            "nonces": dict(self._nonces),
            "supply": sum(self._balances.values()),
        }

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("ledger") != "balance":
            return None
        sender = message.get("sender")
        recipient = message.get("recipient")
        amount = message.get("amount")
        fee = message.get("fee")
        nonce = message.get("nonce")
        if not isinstance(sender, str) or not sender:
            return None
        if not isinstance(recipient, str) or not recipient:
            return None
        if not _is_int(amount) or amount < 1:
            return None
        if not _is_int(fee) or fee < 0:
            return None
        if not _is_int(nonce) or nonce < 0:
            return None
        if nonce != self._nonces.get(sender, 0):
            return None
        if self._balances.get(sender, 0) < amount + fee:
            return None
        if self._balances.get(recipient, 0) + amount > MAX_SAFE_INT:
            return None
        return sender, recipient, amount, fee
