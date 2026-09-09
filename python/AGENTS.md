# AGENTS.md — Python implementation

Read the root `AGENTS.md` first. This file covers only what is specific to `python/`.

## Role: reference implementation

The vectors in `conformance/vectors/` are generated from this package. That makes it the
reference, and it carries two obligations the other implementations do not:

1. **Correctness here becomes correctness everywhere.** A bug that reaches the vectors is
   propagated into Rust and TypeScript as a requirement. Vector-affecting changes need
   proportionate scrutiny.
2. **Reference status is not authority.** The spec is still the source of truth. When
   this package and `SPEC/` disagree, this package is wrong.

## Layout

```
chaincraft_core/
  canonical.py   Canonical JSON encoder and parser (wire-v1 §1)
  envelope.py    Envelope build, serialize, validate (§3)
  framing.py     TCP framing and UDP datagrams (§4)
  control.py     ctl.* control messages (§5)
  crypto.py      BIP-340 Schnorr, Ed25519 (§6)
  ecdsa.py       secp256k1 ECDSA (crypto-ecdsa.md)
  vdf.py         Sloth VDF (crypto-vdf.md)
  vrf.py         Deterministic ECDSA VRF (crypto-vrf.md)
  discovery.py   Address book and local-discovery policy
  consensus_pow.py   Pedagogical PoW object
  consensus_pos.py   Pedagogical PoS object
  consensus_pbft.py  Pedagogical PBFT object
  ledger_balance.py  Pedagogical account ledger
  ledger_utxo.py     Pedagogical UTXO ledger
  dedup.py       Seen-digest set and relay gate (§7)
  memento.py     StateMemento (semantics-v1 §4)
  object.py      SharedObject contract, digests, tie-break (§2, §5, §6)
  pipeline.py    ObjectRegistry, validate-all-then-apply (§3)
  node.py        TCP mesh node for the live interop runner
  features.py    Feature manifest — read by tools/parity_check.py
tests/
  test_level0.py         One test per normative wire rule
  test_level1.py         One test per normative semantics rule
  test_vectors.py        Shared conformance vectors
  conformance_objects.py Level 1 fixtures (semantics-v1 §8)
```

`conformance_objects.py` lives under `tests/` deliberately: the `counter` and `mirror`
objects are conformance scaffolding, not shipped API. `conformance/generate_vectors.py`
adds `python/tests` to `sys.path` to reach them.

## Commands

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
python -m chaincraft_core.features      # feature manifest
black chaincraft_core tests
ruff check chaincraft_core tests
```

## Conventions

- Python 3.9 is the floor. No `match`, no `X | Y` annotations at runtime; keep
  `from __future__ import annotations` at the top of every module.
- **No required third-party dependencies in the Level 0 core.** BIP-340 is implemented in
  pure Python for this reason. Ed25519 uses `cryptography` behind an optional import.
  A dependency here becomes a dependency for everyone embedding Chaincraft.
- Public API is explicit: keep `__all__` accurate.
- Validation raises `CanonicalError` or `ProtocolError`. Signature verification returns
  `False` on malformed input and never raises into the receive path.
- Section references in docstrings point at the spec, for example
  `SPEC/wire-v1.md section 3`.

## When adding a feature

Add the ID to `FEATURES` in `chaincraft_core/features.py` in the same pull request that
implements it. The parity gate cross-checks that list against `SPEC/features.yaml` and
fails on either kind of disagreement.

If this is the first implementation of the feature, extend
`conformance/generate_vectors.py` and regenerate. Vectors must be deterministic — fixed
timestamps, fixed keys, fixed signing nonces — and `test_vectors_are_reproducible`
enforces that.
