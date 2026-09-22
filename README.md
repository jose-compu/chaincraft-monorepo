# Chaincraft Monorepo

Chaincraft in three languages — Python, Rust and TypeScript — held at **100% feature
parity** by a specification, shared conformance vectors, and a CI gate that fails on
drift.

Chaincraft is a platform for blockchain development and prototyping. It gives you a
gossip mesh, a shared-object model, and the consensus, ledger, and cryptographic
primitives a new chain is built from.

---

## Why a monorepo

Three implementations that must agree need to change together. A specification edit, its
conformance vectors and three implementations belong in one commit and one review.
Splitting them across repositories means every cross-language change becomes a
coordination problem, and coordination problems are how parity commitments quietly fail.

## Repository layout

```
SPEC/            Normative specifications — the source of truth
  wire-v1.md       Level 0 — wire protocol, byte-exact
  semantics-v1.md  Level 1 — object and pipeline semantics
  features.yaml    Level 2 — the parity registry
conformance/     Shared golden vectors and the live interop runner
python/          chaincraft-core — reference implementation
rust/            chaincraft-core crate
typescript/      @chaincraft/core
tools/           parity_check.py, sync_gap_issues.py
AGENTS.md        Contributor contract, human and agent alike
ROADMAP.md       The parity commitment and the staged plan
```

---

## Parity

Every capability exists in all three implementations with identical observable
behaviour. Parity is of *behaviour*, not of syntax — each language stays idiomatic in
naming, async model and error representation.

```bash
python3 tools/parity_check.py --summary
```

```
feature                   lvl  python       rust         typescript
----------------------------------------------------------------------
wire.canonical-json       0    yes          yes          yes
wire.payload-digest       0    yes          yes          yes
wire.envelope             0    yes          yes          yes
wire.framing-udp          0    yes          yes          n/a
...
```

The registry lives in `SPEC/features.yaml`, each implementation reports what it provides,
and `tools/parity_check.py` fails CI when the two disagree or when a feature has been
missing from a language for more than 14 days. Gaps become GitHub issues and are
dispatched to coding agents automatically. See `ROADMAP.md` §4.

## Status

| Stage | | |
|---|---|---|
| 1 | Wire and semantics specs | done |
| 2 | Python reference core — Level 0 and Level 1 | done |
| 3 | Parity machinery and conformance vectors | done |
| 4 | TypeScript core — Level 0 and Level 1 | done |
| 5 | Rust core — Level 0 and Level 1 | done |
| 6 | Live 3×3 interop matrix | done |
| 7 | Level 1 replay parity | done |
| 8 | Level 2 feature backfill | done |
| 9 | Mixed-language BitTorrent swarm | done |
| 10 | Address URIs and channel abstraction | done |
| 11 | NAT traversal (STUN, hole punch, relay) | done |

Python, TypeScript and Rust all cover Level 0, Level 1, the Level 2
registry, a BitTorrent swarm, address URIs, and NAT traversal:
33 of 33 features each (TypeScript 32 implemented plus the UDP exemption). The
one exemption in
the registry is `wire.framing-udp` for TypeScript, since browsers have no
raw UDP socket and UDP is optional at Level 0.

TypeScript was written from `SPEC/` alone, without reading the Python source, as a test of
whether the specification was complete. It was not: the exercise found five defects,
including a `wire.dedup` feature that Python's manifest claimed but no implementation
actually had. All five are fixed and pinned by vectors — see `ROADMAP.md` Stage 4.

---

## The wire protocol in one page

Every frame is one envelope, serialized as canonical JSON, length-prefixed on TCP.

```
+-----------------+---------------------------+
| length (4 bytes)| canonical JSON body       |
| big-endian u32  | exactly `length` bytes    |
+-----------------+---------------------------+
```

```json
{"alg":"schnorr","data":{"n":1},"id":"<64 hex>","pk":"<64 hex>","sig":"<128 hex>","ts":1757430000000,"type":"app.counter","v":1}
```

Three properties do most of the work:

- **Canonical JSON.** Sorted keys, no whitespace, no floating point. Non-canonical
  serialization fails silently rather than loudly, so it is pinned by vectors.
- **Content addressing.** `id` is `sha256(canonical_json(data))`. A relay can rebuild an
  envelope without breaking deduplication downstream, which removes the usual
  "relay these bytes verbatim" fragility.
- **Version negotiation.** `ctl.hello` on every connection. A peer speaking a version we
  cannot serve is disconnected cleanly instead of silently misunderstood.

Full detail in `SPEC/wire-v1.md`.

---

## Quick start

```bash
# Python reference implementation
cd python
pip install -e ".[dev]"
python -m pytest tests/ -v
```

```python
from chaincraft_core import Envelope, encode_frame

env = Envelope.build("app.counter", {"by": "alice", "delta": 1})
print(env.id)        # sha256 over the canonical payload
print(env.to_json()) # canonical bytes, keys sorted
frame = encode_frame(env.to_bytes())
```

A protocol implements `receive`. Peers may miss a message. A memento is for a
consensus object, not for a chat room.

```python
from chaincraft_core.object import SharedObject

class Room(SharedObject):
    def __init__(self):
        self.lines = []

    def receive(self, message):
        self.lines.append(message["text"])
```

Rust implements `Protocol`. TypeScript extends `BaseSharedObject` and overrides
`receive`. Reject a message by overriding `is_valid` (`accept` in Rust).

## Development

```bash
# Test suites
cd python && python3 -m pytest tests/ -v
cd rust && cargo test --all-features
cd typescript && npm test

# Conformance vectors across every implementation present
python3 conformance/run_all.py

# Live 3x3 interop matrix
python3 conformance/runner/run_interop.py

# Mixed-language BitTorrent swarm (each language seeds once)
python3 conformance/runner/run_bittorrent.py

# Parity
python3 tools/parity_check.py
python3 tools/parity_check.py --summary
python3 tools/parity_check.py --gaps
```

Regenerating vectors is a deliberate act — a diff under `conformance/vectors/` means the
wire protocol changed:

```bash
python3 conformance/generate_vectors.py
```

## Contributing

Read `AGENTS.md`. It applies to human and agent contributors equally, and covers the five
rules, how to add a feature, how to port one, and the definition of done.

Short version: specify first, implement once, write vectors, port to the other two within
14 days, and update `SPEC/features.yaml` in the same pull request.

## License

MIT
