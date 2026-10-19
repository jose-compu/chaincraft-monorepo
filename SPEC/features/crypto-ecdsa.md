# crypto.ecdsa

**Release:** 1.1.0

ECDSA over secp256k1. Level 2 signing primitive used by ledgers and by `crypto.vrf`.

This is not the Level 0 `wire.sig-schnorr` scheme. The curve is the same; the
encoding and the signed digest are not.

## Algorithm

1. `z = SHA-256(message)` interpreted as a big-endian integer, reduced modulo `n`.
2. Sign `z` with ECDSA, RFC 6979 deterministic `k` (HMAC-SHA256, RFC 6979 §3.2).
3. Normalize `s` to the lower half of the scalar field (`s <= n/2`). A signature
   with high `s` is invalid.
4. Encode as 64 raw bytes: `r || s`, each 32-byte big-endian.
5. Public keys are 33-byte compressed SEC1 points (`0x02`/`0x03` || x).

Secret keys are 32-byte big-endian scalars in `1 .. n-1`.

Verification MUST return false on any malformed input (wrong lengths, point at
infinity, `r` or `s` out of range, high `s`) and MUST NOT raise into a caller.

## Hex on the wire

When a signature or key appears inside canonical JSON it is lowercase hex of the
raw bytes above. 64 hex chars for a secret or `r`/`s` half; 66 for a compressed
public key; 128 for a signature.

## Rejection

| Input | Result |
|---|---|
| public key not 33 bytes, or prefix not `0x02`/`0x03` | invalid |
| signature not 64 bytes | invalid |
| `s > n/2` | invalid |
| point does not lie on secp256k1 | invalid |

`conformance/vectors/ecdsa.json` pins RFC 6979 plus malformed cases.
