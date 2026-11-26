"""Transfer chain — SPEC/features/chain-transfer.md."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import crypto
from .canonical import MAX_SAFE_INT, canonical_bytes, canonical_json
from .object import merkle_digest

__all__ = [
    "TransferChain",
    "block_id",
    "sign_transfer",
    "transaction_id",
    "transfer_signing_bytes",
    "verify_transfer",
]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SIG128 = re.compile(r"^[0-9a-f]{128}$")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def _normalize_genesis(genesis: Mapping[str, int]) -> Dict[str, int]:
    if not genesis:
        raise ValueError("genesis must not be empty")
    out: Dict[str, int] = {}
    for account in sorted(genesis):
        amount = genesis[account]
        if not account:
            raise ValueError("account id must be non-empty")
        if not _is_int(amount) or not (1 <= amount <= MAX_SAFE_INT):
            raise ValueError("each balance must be an integer in 1..2^53-1")
        out[account] = amount
    return out


def transaction_id(body: Mapping[str, Any]) -> str:
    return merkle_digest(dict(body))


def transfer_signing_bytes(body: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(canonical_bytes(body)).digest()


def _parse_body(body: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(body, dict):
        return None
    amount = body.get("amount")
    fee = body.get("fee")
    nonce = body.get("nonce")
    recipient = body.get("recipient")
    sender = body.get("sender")
    if not _is_int(amount) or amount < 1:
        return None
    if not _is_int(fee) or fee < 0:
        return None
    if not _is_int(nonce) or nonce < 0:
        return None
    if not isinstance(recipient, str) or not recipient:
        return None
    if not isinstance(sender, str) or not _HEX64.match(sender):
        return None
    return {
        "amount": amount,
        "fee": fee,
        "nonce": nonce,
        "recipient": recipient,
        "sender": sender,
    }


def verify_transfer(tx: Any) -> bool:
    if not isinstance(tx, dict):
        return False
    signature = tx.get("signature")
    if not isinstance(signature, str) or not _SIG128.match(signature):
        return False
    body = {key: tx[key] for key in tx if key != "signature"}
    parsed = _parse_body(body)
    if parsed is None:
        return False
    try:
        return crypto.verify(
            crypto.SCHNORR,
            transfer_signing_bytes(parsed),
            bytes.fromhex(signature),
            bytes.fromhex(parsed["sender"]),
        )
    except (ValueError, crypto.CryptoUnavailable):
        return False


def sign_transfer(
    body: Mapping[str, Any],
    secret_key: bytes,
    aux: Optional[bytes] = None,
) -> Dict[str, Any]:
    parsed = _parse_body(body)
    if parsed is None:
        raise ValueError("invalid transfer body")
    sig, _pk = crypto.sign(
        crypto.SCHNORR,
        transfer_signing_bytes(parsed),
        secret_key,
        aux,
    )
    return {**parsed, "signature": sig.hex()}


def block_id(header: Mapping[str, Any]) -> str:
    return merkle_digest(dict(header))


class _ChainMempool:
    def __init__(self) -> None:
        self._txs: Dict[str, Dict[str, Any]] = {}

    def submit(self, tx: Dict[str, Any]) -> bool:
        if not verify_transfer(tx):
            return False
        body = {k: tx[k] for k in tx if k != "signature"}
        tid = transaction_id(body)
        self._txs[tid] = dict(tx)
        return True

    def ordered(self) -> List[Dict[str, Any]]:
        items = list(self._txs.values())

        def sort_key(tx: Dict[str, Any]) -> tuple:
            body = {k: tx[k] for k in tx if k != "signature"}
            tid = transaction_id(body)
            return (-int(body["fee"]), tid)

        return sorted(items, key=sort_key)

    def remove(self, ids: Sequence[str]) -> None:
        for tid in ids:
            self._txs.pop(tid, None)


class TransferChain:
    def __init__(
        self,
        genesis: Mapping[str, int],
        reward: int = 0,
        driver: Optional[Any] = None,
    ) -> None:
        if not _is_int(reward) or reward < 0:
            raise ValueError("reward must be >= 0")
        self._genesis = _normalize_genesis(genesis)
        self.reward = reward
        self._driver = driver
        self._blocks: Dict[str, Dict[str, Any]] = {}
        self._mempool = _ChainMempool()
        self._balances: Dict[str, int] = dict(self._genesis)
        self._nonces: Dict[str, int] = {k: 0 for k in self._genesis}
        self._canonical: List[str] = []
        self._height = 0
        self._tip = ""

    def set_driver(self, driver: Any) -> None:
        self._driver = driver

    @property
    def driver(self) -> Any:
        return self._driver

    def submit(self, tx: Any) -> bool:
        if not isinstance(tx, dict):
            return False
        return self._mempool.submit(tx)

    def _snapshot_state(self) -> Dict[str, int]:
        return {
            "balances": dict(sorted(self._balances.items())),
            "nonces": dict(sorted(self._nonces.items())),
            "v": 1,
        }

    def _state_root(self) -> str:
        return merkle_digest(self._snapshot_state())

    def _tx_root(self, txs: Sequence[Dict[str, Any]]) -> str:
        ids = []
        for tx in txs:
            body = {k: tx[k] for k in tx if k != "signature"}
            ids.append(transaction_id(body))
        return merkle_digest(ids)

    def _apply_tx(
        self,
        tx: Dict[str, Any],
        producer: str,
        balances: Dict[str, int],
        nonces: Dict[str, int],
    ) -> bool:
        if not verify_transfer(tx):
            return False
        body = {k: tx[k] for k in tx if k != "signature"}
        sender = body["sender"]
        recipient = body["recipient"]
        amount = body["amount"]
        fee = body["fee"]
        nonce = body["nonce"]
        if nonce != nonces.get(sender, 0):
            return False
        sender_bal = balances.get(sender, 0)
        if sender_bal < amount + fee:
            return False
        if balances.get(recipient, 0) + amount > MAX_SAFE_INT:
            return False
        producer_credit = fee + self.reward
        if balances.get(producer, 0) + producer_credit > MAX_SAFE_INT:
            return False
        balances[sender] = sender_bal - amount - fee
        balances[recipient] = balances.get(recipient, 0) + amount
        balances[producer] = balances.get(producer, 0) + producer_credit
        nonces[sender] = nonce + 1
        if recipient not in nonces:
            nonces[recipient] = 0
        if producer not in nonces:
            nonces[producer] = 0
        return True

    def _apply_block_transactions(
        self,
        txs: Sequence[Dict[str, Any]],
        producer: str,
        balances: Dict[str, int],
        nonces: Dict[str, int],
    ) -> bool:
        for tx in txs:
            if not self._apply_tx(tx, producer, balances, nonces):
                return False
        return True

    def _replay_canonical(self, canon: List[str]) -> None:
        self._balances = dict(self._genesis)
        self._nonces = {k: 0 for k in self._genesis}
        self._canonical = []
        self._height = 0
        self._tip = ""
        for bid in canon:
            block = self._blocks.get(bid)
            if block is None:
                return
            header = block["header"]
            txs = block.get("transactions") or []
            if not self._apply_block_transactions(
                txs, header["producer"], self._balances, self._nonces
            ):
                return
            self._canonical.append(bid)
            self._height = header["height"]
            self._tip = bid

    def _validate_header(self, header: Any, parent_id: str) -> bool:
        if not isinstance(header, dict):
            return False
        height = header.get("height")
        parent = header.get("parent")
        producer = header.get("producer")
        state_root = header.get("state_root")
        time = header.get("time")
        tx_root = header.get("tx_root")
        if not _is_int(height) or height < 1:
            return False
        if not isinstance(parent, str):
            return False
        if not isinstance(producer, str) or not producer:
            return False
        if not isinstance(state_root, str) or not _HEX64.match(state_root):
            return False
        if not _is_int(time) or time < 0:
            return False
        if not isinstance(tx_root, str) or not _HEX64.match(tx_root):
            return False
        if height == 1:
            if parent != "":
                return False
        else:
            if parent != parent_id:
                return False
            if parent_id not in self._blocks:
                return False
        return True

    def _validate_block_record(
        self, block: Dict[str, Any], check_driver: bool = True
    ) -> bool:
        if block.get("chain") != "transfer":
            return False
        header = block.get("header")
        txs = block.get("transactions")
        proof = block.get("proof")
        if not isinstance(txs, list):
            return False
        parent_id = ""
        if isinstance(header, dict) and _is_int(header.get("height")):
            if header["height"] > 1:
                parent_id = header.get("parent") or ""
        if not self._validate_header(header, parent_id):
            return False
        assert isinstance(header, dict)
        bid = block_id(header)
        if bid in self._blocks:
            return False
        for tx in txs:
            if not verify_transfer(tx):
                return False
        if self._tx_root(txs) != header["tx_root"]:
            return False
        balances = dict(self._genesis)
        nonces = {k: 0 for k in self._genesis}
        parent = header["parent"]
        if header["height"] > 1:
            chain_prefix = self._canonical_for_parent(parent)
            for pid in chain_prefix:
                pb = self._blocks[pid]
                if not self._apply_block_transactions(
                    pb.get("transactions") or [],
                    pb["header"]["producer"],
                    balances,
                    nonces,
                ):
                    return False
        if not self._apply_block_transactions(
            txs, header["producer"], balances, nonces
        ):
            return False
        snap = {
            "balances": dict(sorted(balances.items())),
            "nonces": dict(sorted(nonces.items())),
            "v": 1,
        }
        if merkle_digest(snap) != header["state_root"]:
            return False
        if check_driver and self._driver is not None:
            if not self._driver.authorize(block, proof):
                return False
        return True

    def _canonical_for_parent(self, parent_id: str) -> List[str]:
        if not parent_id:
            return []
        if self._driver is not None:
            canon = self._driver.canonical()
            if parent_id in canon:
                idx = canon.index(parent_id)
                return canon[: idx + 1]
        chain: List[str] = []
        cursor = parent_id
        while cursor:
            chain.append(cursor)
            block = self._blocks.get(cursor)
            if block is None:
                break
            cursor = block["header"]["parent"]
        chain.reverse()
        return chain

    def accept_block(self, block: Any) -> bool:
        if not isinstance(block, dict):
            return False
        if not self._validate_block_record(block):
            return False
        header = block["header"]
        bid = block_id(header)
        self._blocks[bid] = block
        if self._driver is not None:
            canon = self._driver.canonical()
            self._replay_canonical(canon)
        else:
            self._replay_canonical(self._extend_canonical(bid))
        return True

    def _extend_canonical(self, bid: str) -> List[str]:
        chain: List[str] = []
        cursor = bid
        while cursor:
            chain.append(cursor)
            block = self._blocks.get(cursor)
            if block is None:
                break
            cursor = block["header"]["parent"]
        chain.reverse()
        return chain

    def produce(self, time: int, producer: str) -> Optional[Dict[str, Any]]:
        if not _is_int(time) or time < 0:
            raise ValueError("time must be >= 0")
        if not producer:
            raise ValueError("producer required")
        parent = self._tip
        height = self._height + 1
        balances = dict(self._balances)
        nonces = dict(self._nonces)
        included: List[Dict[str, Any]] = []
        included_ids: List[str] = []
        for tx in self._mempool.ordered():
            body = {k: tx[k] for k in tx if k != "signature"}
            tid = transaction_id(body)
            trial_bal = dict(balances)
            trial_non = dict(nonces)
            if self._apply_tx(tx, producer, trial_bal, trial_non):
                included.append(tx)
                included_ids.append(tid)
                balances = trial_bal
                nonces = trial_non
            else:
                break
        snap = {
            "balances": dict(sorted(balances.items())),
            "nonces": dict(sorted(nonces.items())),
            "v": 1,
        }
        header = {
            "height": height,
            "parent": parent,
            "producer": producer,
            "state_root": merkle_digest(snap),
            "time": time,
            "tx_root": self._tx_root(included),
        }
        block: Dict[str, Any] = {
            "chain": "transfer",
            "header": header,
            "transactions": included,
            "proof": {},
        }
        if self._driver is not None:
            proof = self._driver.build_proof(block)
            block["proof"] = proof
        if not self.accept_block(block):
            return None
        self._mempool.remove(included_ids)
        return block

    def import_blocks(self, blocks: Sequence[Dict[str, Any]]) -> bool:
        for block in blocks:
            if not self.accept_block(block):
                return False
        return True

    def state(self) -> Dict[str, Any]:
        return {
            "balances": dict(self._balances),
            "nonces": dict(self._nonces),
            "canonical": list(self._canonical),
            "height": self._height,
            "tip": self._tip,
        }