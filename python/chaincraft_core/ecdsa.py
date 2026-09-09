"""secp256k1 ECDSA — SPEC/features/crypto-ecdsa.md."""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional, Tuple

from .crypto import _G, _N, _P, _lift_x, _point_add, _point_mul

__all__ = ["sign", "verify", "public_key", "N"]

N = _N
_HALF_N = _N // 2


def _int_be(data: bytes) -> int:
    return int.from_bytes(data, "big")


def _u32(value: int) -> bytes:
    return value.to_bytes(32, "big")


def public_key(secret_key: bytes) -> bytes:
    if len(secret_key) != 32:
        raise ValueError("secret key must be 32 bytes")
    d = _int_be(secret_key)
    if not (1 <= d < _N):
        raise ValueError("secret key out of range")
    point = _point_mul(_G, d)
    if point is None:
        raise ValueError("invalid secret key")
    x, y = point
    return bytes([0x02 + (y & 1)]) + _u32(x)


def _decompress(pubkey: bytes) -> Optional[Tuple[int, int]]:
    if len(pubkey) != 33 or pubkey[0] not in (0x02, 0x03):
        return None
    point = _lift_x(_int_be(pubkey[1:]))
    if point is None:
        return None
    x, y = point
    if (y & 1) != (pubkey[0] - 0x02):
        y = _P - y
    return (x, y)


def _rfc6979_ks(secret: int, z: int):
    """Yield candidate k values per RFC 6979 §3.2, HMAC-SHA256."""
    h1 = _u32(z)
    x = _u32(secret)
    v = b"\x01" * 32
    key = b"\x00" * 32
    key = hmac.new(key, v + b"\x00" + x + h1, hashlib.sha256).digest()
    v = hmac.new(key, v, hashlib.sha256).digest()
    key = hmac.new(key, v + b"\x01" + x + h1, hashlib.sha256).digest()
    v = hmac.new(key, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(key, v, hashlib.sha256).digest()
        candidate = _int_be(v)
        if 1 <= candidate < _N:
            yield candidate
        key = hmac.new(key, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(key, v, hashlib.sha256).digest()


def sign(message: bytes, secret_key: bytes) -> bytes:
    if len(secret_key) != 32:
        raise ValueError("secret key must be 32 bytes")
    d = _int_be(secret_key)
    if not (1 <= d < _N):
        raise ValueError("secret key out of range")
    z = _int_be(hashlib.sha256(message).digest()) % _N
    for k in _rfc6979_ks(d, z):
        point = _point_mul(_G, k)
        if point is None:
            continue
        r = point[0] % _N
        if r == 0:
            continue
        s = (pow(k, _N - 2, _N) * (z + r * d)) % _N
        if s == 0:
            continue
        if s > _HALF_N:
            s = _N - s
        return _u32(r) + _u32(s)
    raise RuntimeError("RFC 6979 failed to produce a k")


def verify(message: bytes, signature: bytes, pubkey: bytes) -> bool:
    try:
        if len(signature) != 64:
            return False
        r = _int_be(signature[:32])
        s = _int_be(signature[32:])
        if not (1 <= r < _N and 1 <= s <= _HALF_N):
            return False
        point = _decompress(pubkey)
        if point is None:
            return False
        z = _int_be(hashlib.sha256(message).digest()) % _N
        w = pow(s, _N - 2, _N)
        u1 = (z * w) % _N
        u2 = (r * w) % _N
        r_point = _point_add(_point_mul(_G, u1), _point_mul(point, u2))
        if r_point is None:
            return False
        return (r_point[0] % _N) == r
    except Exception:
        return False
