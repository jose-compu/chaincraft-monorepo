"""Sloth VDF — SPEC/features/crypto-vdf.md."""

from __future__ import annotations

P = 64106875808534963770974826322234655855469213855659218736479077548818158667371

__all__ = ["P", "evaluate", "verify", "proof_to_hex", "hex_to_proof"]


def _is_residue(x: int) -> bool:
    return pow(x, (P - 1) // 2, P) == 1


def _mod_sqrt_op(x: int) -> int:
    if _is_residue(x):
        return pow(x, (P + 1) // 4, P)
    return pow((-x) % P, (P + 1) // 4, P)


def _seed_int(seed: bytes) -> int:
    return int.from_bytes(seed, "big") % P


def evaluate(seed: bytes, t: int) -> int:
    if t < 1:
        raise ValueError("t must be a positive integer")
    x = _seed_int(seed)
    for _ in range(t):
        x = _mod_sqrt_op(x)
    return x


def verify(seed: bytes, t: int, proof: int) -> bool:
    try:
        if t < 1 or proof < 0 or proof >= P:
            return False
        x = _seed_int(seed)
        y = proof
        for _ in range(t):
            y = pow(y, 2, P)
        if not _is_residue(y):
            y = (-y) % P
        return y == x or y == ((-x) % P)
    except Exception:
        return False


def proof_to_hex(proof: int) -> str:
    if proof == 0:
        return "0"
    return format(proof, "x")


def hex_to_proof(text: str) -> int:
    return int(text, 16)
