# crypto.vrf

**Release:** 1.10.0

Deterministic uniqueness VRF built on `crypto.ecdsa`.

This is a prototype VRF: uniqueness comes from RFC 6979, not from a
hash-to-curve construction. It is specified here because the legacy
`ECDSAVRFPrimitive` used non-deterministic DER signatures and could not
interoperate. A later revision MAY replace this with RFC 9381; the feature id
stays `crypto.vrf`.

## Evaluate

```
digest  = SHA-256(  "chaincraft-vrf-v1" || message  )
proof   = ecdsa_sign(sk, digest)          # 64-byte compact, low-S
output  = SHA-256( proof || pk || message )   # 32 bytes
```

`pk` is the 33-byte compressed public key of `sk`. The domain string is the
17-byte ASCII prefix `chaincraft-vrf-v1` with no terminator.

## Verify

1. Reject unless `ecdsa_verify(pk, digest, proof)` is true, with
   `digest = SHA-256("chaincraft-vrf-v1" || message)`.
2. `output = SHA-256(proof || pk || message)`.

The same `(sk, message)` MUST always yield the same `(proof, output)`.
Verification MUST return false on malformed input and MUST NOT raise.

## Encoding

`proof` and `output` are lowercase hex (128 and 64 characters). `pk` is 66
lowercase hex characters.

`conformance/vectors/vrf.json` pins evaluate, uniqueness and rejection.
