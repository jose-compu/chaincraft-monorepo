"""Deterministic ECDSA VRF — SPEC/features/crypto-vrf.md."""

from __future__ import annotations

import hashlib
from typing import Optional, Tuple

from . import ecdsa

__all__ = ["DOMAIN", "evaluate", "verify"]

DOMAIN = b"chaincraft-vrf-v1"


def _digest(message: bytes) -> bytes:
    return hashlib.sha256(DOMAIN + message).digest()


def _output(proof: bytes, pubkey: bytes, message: bytes) -> bytes:
    return hashlib.sha256(proof + pubkey + message).digest()


def evaluate(message: bytes, secret_key: bytes) -> Tuple[bytes, bytes, bytes]:
    """Return ``(proof, output, pubkey)``."""
    pubkey = ecdsa.public_key(secret_key)
    proof = ecdsa.sign(_digest(message), secret_key)
    return proof, _output(proof, pubkey, message), pubkey


def verify(
    message: bytes,
    proof: bytes,
    pubkey: bytes,
    output: Optional[bytes] = None,
) -> bool:
    try:
        if not ecdsa.verify(_digest(message), proof, pubkey):
            return False
        computed = _output(proof, pubkey, message)
        if output is not None and output != computed:
            return False
        return True
    except Exception:
        return False
