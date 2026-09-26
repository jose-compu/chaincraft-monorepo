"""Signature schemes — SPEC/wire-v1.md section 6.

BIP-340 Schnorr is implemented in pure Python so a Level 0 core has zero native
dependencies. Ed25519 delegates to ``cryptography`` when installed.

Verification never raises into the receive path: malformed input returns False.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Optional, Tuple

__all__ = ["verify", "sign", "public_key", "SCHNORR", "ED25519", "CryptoUnavailable"]

SCHNORR = "schnorr"
ED25519 = "ed25519"


class CryptoUnavailable(RuntimeError):
    """The backend for the requested algorithm is not installed."""


# --------------------------------------------------------------------------
# BIP-340 Schnorr over secp256k1 (pure Python, adapted from the BIP reference)
# --------------------------------------------------------------------------

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)

Point = Optional[Tuple[int, int]]


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    tag_hash = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(tag_hash + tag_hash + msg).digest()


def _point_add(p1: Point, p2: Point) -> Point:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    if p1[0] == p2[0] and p1[1] != p2[1]:
        return None
    if p1 == p2:
        lam = (3 * p1[0] * p1[0] * pow(2 * p1[1], _P - 2, _P)) % _P
    else:
        lam = ((p2[1] - p1[1]) * pow(p2[0] - p1[0], _P - 2, _P)) % _P
    x3 = (lam * lam - p1[0] - p2[0]) % _P
    return (x3, (lam * (p1[0] - x3) - p1[1]) % _P)


def _point_mul(point: Point, scalar: int) -> Point:
    result: Point = None
    for i in range(256):
        if (scalar >> i) & 1:
            result = _point_add(result, point)
        point = _point_add(point, point)
    return result


def _lift_x(x: int) -> Point:
    if x >= _P:
        return None
    y_sq = (pow(x, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != y_sq:
        return None
    return (x, y if y % 2 == 0 else _P - y)


def _schnorr_verify(msg32: bytes, sig64: bytes, pubkey32: bytes) -> bool:
    if len(msg32) != 32 or len(sig64) != 64 or len(pubkey32) != 32:
        return False
    point = _lift_x(int.from_bytes(pubkey32, "big"))
    if point is None:
        return False
    r = int.from_bytes(sig64[:32], "big")
    s = int.from_bytes(sig64[32:], "big")
    if r >= _P or s >= _N:
        return False
    e = (
        int.from_bytes(
            _tagged_hash("BIP0340/challenge", sig64[:32] + pubkey32 + msg32), "big"
        )
        % _N
    )
    result = _point_add(_point_mul(_G, s), _point_mul(point, _N - e))
    if result is None or result[1] % 2 != 0 or result[0] != r:
        return False
    return True


def _schnorr_pubkey(seckey32: bytes) -> bytes:
    d = int.from_bytes(seckey32, "big")
    if not 1 <= d <= _N - 1:
        raise ValueError("secret key out of range")
    point = _point_mul(_G, d)
    assert point is not None
    return point[0].to_bytes(32, "big")


def _schnorr_sign(msg32: bytes, seckey32: bytes, aux32: Optional[bytes] = None) -> bytes:
    if len(msg32) != 32:
        raise ValueError("message must be 32 bytes")
    d0 = int.from_bytes(seckey32, "big")
    if not 1 <= d0 <= _N - 1:
        raise ValueError("secret key out of range")
    point = _point_mul(_G, d0)
    assert point is not None
    d = d0 if point[1] % 2 == 0 else _N - d0
    if aux32 is None:
        aux32 = secrets.token_bytes(32)
    t = (d ^ int.from_bytes(_tagged_hash("BIP0340/aux", aux32), "big")).to_bytes(32, "big")
    k0 = (
        int.from_bytes(
            _tagged_hash("BIP0340/nonce", t + point[0].to_bytes(32, "big") + msg32),
            "big",
        )
        % _N
    )
    if k0 == 0:
        raise RuntimeError("nonce is zero")
    nonce_point = _point_mul(_G, k0)
    assert nonce_point is not None
    k = k0 if nonce_point[1] % 2 == 0 else _N - k0
    rx = nonce_point[0].to_bytes(32, "big")
    e = (
        int.from_bytes(
            _tagged_hash(
                "BIP0340/challenge", rx + point[0].to_bytes(32, "big") + msg32
            ),
            "big",
        )
        % _N
    )
    return rx + ((k + e * d) % _N).to_bytes(32, "big")


# --------------------------------------------------------------------------
# Ed25519 (optional backend)
# --------------------------------------------------------------------------


def _ed25519_backend():
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise CryptoUnavailable(
            "ed25519 requires the 'cryptography' package: pip install chaincraft-core[ed25519]"
        ) from exc
    return ed25519


def ed25519_available() -> bool:
    try:
        _ed25519_backend()
    except CryptoUnavailable:
        return False
    return True


# --------------------------------------------------------------------------
# Public surface
# --------------------------------------------------------------------------


def verify(alg: str, message32: bytes, signature: bytes, pubkey: bytes) -> bool:
    """Verify a signature. Returns False on malformed input, never raises."""
    try:
        if alg == SCHNORR:
            return _schnorr_verify(message32, signature, pubkey)
        if alg == ED25519:
            ed25519 = _ed25519_backend()
            if len(pubkey) != 32 or len(signature) != 64:
                return False
            key = ed25519.Ed25519PublicKey.from_public_bytes(pubkey)
            key.verify(signature, message32)
            return True
        return False
    except CryptoUnavailable:
        raise
    except Exception:
        return False


def sign(alg: str, message32: bytes, secret_key: bytes) -> Tuple[bytes, bytes]:
    """Sign ``message32``. Returns ``(signature, public_key)``."""
    if alg == SCHNORR:
        return _schnorr_sign(message32, secret_key), _schnorr_pubkey(secret_key)
    if alg == ED25519:
        ed25519 = _ed25519_backend()
        key = ed25519.Ed25519PrivateKey.from_private_bytes(secret_key)
        from cryptography.hazmat.primitives import serialization

        pub = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return key.sign(message32), pub
    raise ValueError(f"unknown algorithm: {alg}")


def public_key(alg: str, secret_key: bytes) -> bytes:
    if alg == SCHNORR:
        return _schnorr_pubkey(secret_key)
    if alg == ED25519:
        return sign(alg, b"\x00" * 32, secret_key)[1]
    raise ValueError(f"unknown algorithm: {alg}")
