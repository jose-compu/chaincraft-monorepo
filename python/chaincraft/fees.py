"""Fee policy — SPEC/features/fees-policy.md."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

__all__ = ["charge", "estimate", "next_base_fee", "select"]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def select(candidates: Sequence[Any], limit: int) -> List[str]:
    if not _is_int(limit) or limit < 1:
        raise ValueError("limit must be >= 1")
    seen = set()
    ranked: List[tuple] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        txid = item.get("id")
        fee = item.get("fee")
        if not isinstance(txid, str) or not txid:
            continue
        if not _is_int(fee) or fee < 0:
            continue
        if txid in seen:
            continue
        seen.add(txid)
        ranked.append((txid, fee))
    ranked.sort(key=lambda row: (-row[1], row[0]))
    return [txid for txid, _fee in ranked[:limit]]


def charge(fee: int, base: int) -> Dict[str, int]:
    if not _is_int(fee) or fee < 0 or not _is_int(base) or base < 0:
        raise ValueError("fee and base must be integers >= 0")
    burned = fee if fee < base else base
    return {"burned": burned, "charged": fee, "tip": fee - burned}


def estimate(fees: Sequence[Any]) -> int:
    values: List[int] = []
    for item in fees:
        if not _is_int(item) or item < 0:
            raise ValueError("fees must be integers >= 0")
        values.append(item)
    if not values:
        return 0
    values.sort()
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) // 2


def next_base_fee(base: int, parent_count: int, target: int) -> int:
    if not _is_int(base) or base < 0:
        raise ValueError("base must be >= 0")
    if not _is_int(parent_count) or parent_count < 0:
        raise ValueError("parent_count must be >= 0")
    if not _is_int(target) or target < 1:
        raise ValueError("target must be >= 1")
    denom = target * 8
    if parent_count >= target:
        nxt = base + base * (parent_count - target) // denom
    else:
        nxt = base - base * (target - parent_count) // denom
    return 1 if nxt < 1 else nxt
