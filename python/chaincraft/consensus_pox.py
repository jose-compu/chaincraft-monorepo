"""Proof-of-transfer object — SPEC/features/consensus-pox.md."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = [
    "ProofOfTransfer",
    "stack_id",
    "bid_id",
    "tenure_id",
    "sortition_score",
]

_SEED_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_INT = 9007199254740991


def _is_int(value: Any) -> bool:
    return (
        isinstance(value, int)
        and value is not True
        and value is not False
        and 0 <= value <= _MAX_INT
    )


def stack_id(locker: str, amount: int, reward_cycle: int) -> str:
    return merkle_digest(
        {"amount": amount, "kind": "stack", "locker": locker, "reward_cycle": reward_cycle}
    )


def bid_id(miner: str, btc_out: int, block_height: int) -> str:
    return merkle_digest(
        {
            "block_height": block_height,
            "btc_out": btc_out,
            "kind": "bid",
            "miner": miner,
        }
    )


def tenure_id(winner: str, prev: str, block_height: int) -> str:
    return merkle_digest(
        {
            "block_height": block_height,
            "kind": "tenure",
            "prev": prev,
            "winner": winner,
        }
    )


def sortition_score(seed: str, miner: str, btc_out: int, block_height: int) -> str:
    return merkle_digest(
        {
            "block_height": block_height,
            "btc_out": btc_out,
            "miner": miner,
            "seed": seed,
        }
    )


def reward_cycle(height: int, cycle_length: int) -> int:
    if height < 1:
        return 0
    return (height - 1) // cycle_length


class ProofOfTransfer(SharedObject):
    def __init__(
        self,
        seed: str,
        cycle_length: int,
        stackers: Sequence[Tuple[str, int]],
    ) -> None:
        if not isinstance(seed, str) or not _SEED_RE.match(seed):
            raise ValueError("seed must be 64 lowercase hex characters")
        if not _is_int(cycle_length) or cycle_length < 1:
            raise ValueError("cycle_length must be an integer >= 1")
        if not stackers:
            raise ValueError("stackers must be non-empty")
        seen: set[str] = set()
        snapshot0: List[Dict[str, Any]] = []
        for locker, amount in stackers:
            if not isinstance(locker, str) or not locker:
                raise ValueError("each locker must be a non-empty string")
            if not _is_int(amount) or amount < 1:
                raise ValueError("each amount must be an integer >= 1")
            if locker in seen:
                raise ValueError("lockers must be distinct")
            seen.add(locker)
            snapshot0.append({"locker": locker, "amount": amount})
        self.seed = seed
        self.cycle_length = cycle_length
        self._snapshot0 = snapshot0
        self._stacks: Dict[str, Dict[str, Any]] = {}
        self._stack_order: List[str] = []
        self._stacks_by_cycle: Dict[int, set[str]] = {}
        self._bids: Dict[str, Dict[str, Any]] = {}
        self._bid_order: List[str] = []
        self._bids_by_height: Dict[int, Dict[str, str]] = {}
        self._tenures: Dict[str, Dict[str, Any]] = {}
        self._tenure_order: List[str] = []
        self._open_height = 1

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        parsed = self._parse(message)
        if parsed is None:
            return self.emit_state_memento()
        kind, digest, record = parsed
        if kind == "stack":
            self._stacks[digest] = record
            self._stack_order.append(digest)
            cycle = record["reward_cycle"]
            self._stacks_by_cycle.setdefault(cycle, set()).add(record["locker"])
        elif kind == "bid":
            self._bids[digest] = record
            self._bid_order.append(digest)
            height = record["block_height"]
            self._bids_by_height.setdefault(height, {})[record["miner"]] = digest
        else:
            self._tenures[digest] = record
            self._tenure_order.append(digest)
            self._open_height = record["block_height"] + 1
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
        open_height = self._open_height
        return {
            "height": height,
            "tip": tip,
            "open_height": open_height,
            "cycle": reward_cycle(open_height, self.cycle_length),
            "canonical": self._canonical(tip),
            "tenures": list(self._tenure_order),
            "bids": list(self._bid_order),
            "stacks": list(self._stack_order),
        }

    def _tip(self) -> Tuple[str, int]:
        if not self._tenures:
            return "", 0
        best = ""
        best_height = -1
        for digest, record in self._tenures.items():
            h = record["block_height"]
            if h > best_height or (h == best_height and (not best or digest < best)):
                best = digest
                best_height = h
        return best, best_height

    def _canonical(self, tip: str) -> List[str]:
        chain: List[str] = []
        cursor = tip
        while cursor:
            chain.append(cursor)
            cursor = self._tenures[cursor]["prev"]
        chain.reverse()
        return chain

    def _snapshot(self, cycle: int) -> List[Dict[str, Any]]:
        if cycle == 0:
            return list(self._snapshot0)
        lockers: List[Dict[str, Any]] = []
        for digest in self._stack_order:
            record = self._stacks[digest]
            if record["reward_cycle"] == cycle:
                lockers.append(
                    {"locker": record["locker"], "amount": record["amount"]}
                )
        return lockers

    def _snapshot_lockers(self, cycle: int) -> set[str]:
        snap = self._snapshot(cycle)
        return {entry["locker"] for entry in snap}

    def _elected_miner(self, block_height: int) -> Optional[str]:
        miners = self._bids_by_height.get(block_height, {})
        if not miners:
            return None
        best_miner: Optional[str] = None
        best_score = ""
        best_id = ""
        for miner, digest in miners.items():
            record = self._bids[digest]
            score = sortition_score(
                self.seed, miner, record["btc_out"], block_height
            )
            if (
                best_miner is None
                or score < best_score
                or (score == best_score and digest < best_id)
            ):
                best_miner = miner
                best_score = score
                best_id = digest
        return best_miner

    def _all_ids(self) -> set[str]:
        return (
            set(self._stacks)
            | set(self._bids)
            | set(self._tenures)
        )

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("consensus") != "pox":
            return None
        kind = message.get("kind")
        if kind == "stack":
            return self._parse_stack(message)
        if kind == "bid":
            return self._parse_bid(message)
        if kind == "tenure":
            return self._parse_tenure(message)
        return None

    def _parse_stack(self, message: Dict[str, Any]):
        locker = message.get("locker")
        amount = message.get("amount")
        reward_cycle_val = message.get("reward_cycle")
        if not isinstance(locker, str) or not locker:
            return None
        if not _is_int(amount) or amount < 1:
            return None
        if not _is_int(reward_cycle_val) or reward_cycle_val < 1:
            return None
        open_cycle = reward_cycle(self._open_height, self.cycle_length)
        if reward_cycle_val <= open_cycle:
            return None
        if locker in self._stacks_by_cycle.get(reward_cycle_val, set()):
            return None
        digest = stack_id(locker, amount, reward_cycle_val)
        if digest in self._all_ids():
            return None
        record = {
            "locker": locker,
            "amount": amount,
            "reward_cycle": reward_cycle_val,
        }
        return ("stack", digest, record)

    def _parse_bid(self, message: Dict[str, Any]):
        miner = message.get("miner")
        btc_out = message.get("btc_out")
        block_height = message.get("block_height")
        if not isinstance(miner, str) or not miner:
            return None
        if not _is_int(btc_out) or btc_out < 1:
            return None
        if not _is_int(block_height) or block_height != self._open_height:
            return None
        cycle = reward_cycle(block_height, self.cycle_length)
        if miner not in self._snapshot_lockers(cycle):
            return None
        if miner in self._bids_by_height.get(block_height, {}):
            return None
        digest = bid_id(miner, btc_out, block_height)
        if digest in self._all_ids():
            return None
        record = {
            "miner": miner,
            "btc_out": btc_out,
            "block_height": block_height,
        }
        return ("bid", digest, record)

    def _parse_tenure(self, message: Dict[str, Any]):
        winner = message.get("winner")
        prev = message.get("prev")
        block_height = message.get("block_height")
        if not isinstance(winner, str) or not winner:
            return None
        if not isinstance(prev, str):
            return None
        if not _is_int(block_height) or block_height != self._open_height:
            return None
        elected = self._elected_miner(block_height)
        if elected is None or winner != elected:
            return None
        tip, _ = self._tip()
        if block_height == 1:
            if prev != "":
                return None
        else:
            if prev != tip:
                return None
        digest = tenure_id(winner, prev, block_height)
        if digest in self._all_ids():
            return None
        record = {
            "winner": winner,
            "prev": prev,
            "block_height": block_height,
        }
        return ("tenure", digest, record)