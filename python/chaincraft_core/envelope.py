"""Envelope — SPEC/wire-v1.md section 3."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .canonical import (
    CanonicalError,
    canonical_bytes,
    canonical_json,
    parse_json,
    payload_digest,
)

__all__ = [
    "ProtocolError",
    "Envelope",
    "PROTOCOL_VERSION",
    "MAX_FUTURE_SKEW_MS",
]

PROTOCOL_VERSION = 1
MAX_FUTURE_SKEW_MS = 300_000  # 5 minutes

_ALLOWED_FIELDS = frozenset({"v", "type", "data", "id", "ts", "sig", "pk", "alg"})
_REQUIRED_FIELDS = frozenset({"v", "type", "data", "id", "ts"})
_TYPE_RE = re.compile(r"^[a-z0-9._-]{1,64}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX128_RE = re.compile(r"^[0-9a-f]{128}$")
_ALGORITHMS = frozenset({"schnorr", "ed25519"})


class ProtocolError(ValueError):
    """Envelope violates the wire protocol."""


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class Envelope:
    type: str
    data: Any
    id: str
    ts: int
    v: int = PROTOCOL_VERSION
    sig: Optional[str] = None
    pk: Optional[str] = None
    alg: Optional[str] = None

    # --- construction -------------------------------------------------

    @classmethod
    def build(
        cls,
        type: str,
        data: Any,
        *,
        ts: Optional[int] = None,
        sig: Optional[str] = None,
        pk: Optional[str] = None,
        alg: Optional[str] = None,
    ) -> "Envelope":
        """Build an envelope, computing the payload digest."""
        if not isinstance(type, str) or not _TYPE_RE.match(type):
            raise ProtocolError(f"invalid type: {type!r}")
        try:
            digest = payload_digest(data)
        except CanonicalError as exc:
            raise ProtocolError(str(exc)) from exc
        return cls(
            type=type,
            data=data,
            id=digest,
            ts=_now_ms() if ts is None else int(ts),
            v=PROTOCOL_VERSION,
            sig=sig,
            pk=pk,
            alg=alg,
        )

    # --- serialization ------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "v": self.v,
            "type": self.type,
            "data": self.data,
            "id": self.id,
            "ts": self.ts,
        }
        if self.sig is not None:
            out["sig"] = self.sig
        if self.pk is not None:
            out["pk"] = self.pk
        if self.alg is not None:
            out["alg"] = self.alg
        return out

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    # --- parsing ------------------------------------------------------

    @classmethod
    def parse(cls, raw: Any, *, now_ms: Optional[int] = None) -> "Envelope":
        """Validate and parse an envelope. Order follows wire-v1.md section 3.3."""
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProtocolError("body is not valid UTF-8") from exc
        if isinstance(raw, str):
            try:
                obj = parse_json(raw)
            except CanonicalError as exc:
                raise ProtocolError(str(exc)) from exc
        else:
            obj = raw

        if not isinstance(obj, dict):
            raise ProtocolError("envelope must be a JSON object")

        keys = set(obj.keys())
        unknown = keys - _ALLOWED_FIELDS
        if unknown:
            raise ProtocolError(f"unknown envelope fields: {sorted(unknown)}")
        missing = _REQUIRED_FIELDS - keys
        if missing:
            raise ProtocolError(f"missing envelope fields: {sorted(missing)}")

        version = obj["v"]
        if version is True or version is False or not isinstance(version, int):
            raise ProtocolError("v must be an integer")
        if version != PROTOCOL_VERSION:
            raise ProtocolError(f"unsupported protocol version: {version}")

        type_ = obj["type"]
        if not isinstance(type_, str) or not _TYPE_RE.match(type_):
            raise ProtocolError(f"invalid type: {type_!r}")

        ts = obj["ts"]
        if ts is True or ts is False or not isinstance(ts, int):
            raise ProtocolError("ts must be an integer")
        if ts < 0:
            raise ProtocolError("ts must be non-negative")
        reference = _now_ms() if now_ms is None else now_ms
        if ts > reference + MAX_FUTURE_SKEW_MS:
            raise ProtocolError("ts is too far in the future")

        eid = obj["id"]
        if not isinstance(eid, str) or not _HEX64_RE.match(eid):
            raise ProtocolError("id must be 64 lowercase hex characters")

        data = obj["data"]
        try:
            computed = payload_digest(data)
        except CanonicalError as exc:
            raise ProtocolError(str(exc)) from exc
        if computed != eid:
            raise ProtocolError("id does not match the payload digest")

        sig = obj.get("sig")
        pk = obj.get("pk")
        alg = obj.get("alg")
        if sig is not None:
            if not isinstance(sig, str) or not _HEX128_RE.match(sig):
                raise ProtocolError("sig must be 128 lowercase hex characters")
            if not isinstance(pk, str) or not _HEX64_RE.match(pk):
                raise ProtocolError("pk must be 64 lowercase hex characters")
            if alg not in _ALGORITHMS:
                raise ProtocolError(f"alg must be one of {sorted(_ALGORITHMS)}")
        elif pk is not None or alg is not None:
            raise ProtocolError("pk and alg require sig")

        return cls(
            type=type_, data=data, id=eid, ts=ts, v=version, sig=sig, pk=pk, alg=alg
        )

    # --- signatures ---------------------------------------------------

    def signing_bytes(self) -> bytes:
        """The 32 raw bytes signed: the hex-decoded id. Never hashed again."""
        return bytes.fromhex(self.id)

    def verify(self) -> bool:
        """Verify the signature. Returns False on any malformed input."""
        if self.sig is None or self.pk is None or self.alg is None:
            return False
        from . import crypto

        return crypto.verify(
            self.alg,
            self.signing_bytes(),
            bytes.fromhex(self.sig),
            bytes.fromhex(self.pk),
        )

    def signed(self, alg: str, secret_key: bytes) -> "Envelope":
        """Return a copy carrying a signature over this envelope's id."""
        from . import crypto

        sig, pk = crypto.sign(alg, self.signing_bytes(), secret_key)
        return Envelope(
            type=self.type,
            data=self.data,
            id=self.id,
            ts=self.ts,
            v=self.v,
            sig=sig.hex(),
            pk=pk.hex(),
            alg=alg,
        )

    def is_control(self) -> bool:
        return self.type.startswith("ctl.")
