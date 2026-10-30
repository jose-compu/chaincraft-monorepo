# Chaincraft Monorepo

Open-source toolkit for peer-to-peer protocols like blockchains, chat rooms,
BitTorrent swarms, and content-addressed stores. Three languages — Python, Rust
and TypeScript — held at **100% feature parity** by a specification, shared
conformance vectors, and a CI gate that fails on drift.

The ordinary object is local: a chat room, a publish-subscribe topic, a
BitTorrent swarm, or a content-addressed store. A node applies the messages it
has. A gap after a disconnect is allowed.

Consensus is a feature class in the same library, not the default. Proof of
work, proof of stake, PBFT, and the Avalanche family, with a balance or UTXO
ledger, are there when the protocol must agree on a head. Those objects keep a
snapshot and may sync it with one peer. The others do not.

Every protocol has two paths. Gossip is relayed. Control (`link.*`) is written
to one peer and is not relayed. `ctl.*` remains the mesh's own control channel.

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
python/          chaincraft — reference implementation
rust/            chaincraft crate
typescript/      @chaincraft/core (npm)
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
| 12 | Hybrid mesh (TCP and UDP hops) | done |
| 13 | Avalanche family and CRDT key-value | done |

Python, TypeScript and Rust all cover Level 0, Level 1, the Level 2
registry, a BitTorrent swarm, address URIs, NAT traversal, Avalanche,
and a last-write-wins CRDT:
44 of 44 features each (TypeScript 43 implemented plus the UDP framing exemption).
The spec release is 1.4.0 (`SPEC/release.yaml`). The wire protocol number stays 1.
Git tag [`v1.4.0`](https://github.com/jose-compu/chaincraft-monorepo/releases/tag/v1.4.0).
[PyPI `chaincraft` 1.4.0](https://pypi.org/project/chaincraft/1.4.0/),
[crates.io `chaincraft` 1.4.0](https://crates.io/crates/chaincraft) and
[npm `@chaincraft/core` 1.4.0](https://www.npmjs.com/package/@chaincraft/core).
`@chaincraft/core/browser` fetches a PeerJS id and does not import the TCP mesh.
The default broker is `https://dechess-org-peerjs.vercel.app`.
The one exemption in the registry is `wire.framing-udp` for TypeScript, since browsers have no
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
- **Two paths.** Gossip (`app.*`) is relayed. Control (`link.*`, and the mesh's
  `ctl.*`) is delivered only on the peer link it arrived on.

Full detail in `SPEC/wire-v1.md`.

---

## Install

```bash
pip install chaincraft
cargo add chaincraft
cargo install chaincraft
npm install @chaincraft/core
```

The node CLIs are `python3 -m chaincraft.node`, `chaincraft-node`, and
`chaincraft-ts-node` (`npm install --global @chaincraft/core`). Default listen
is `0.0.0.0:9735`. Local Hello World still dials `127.0.0.1:9735`.

Ed25519 is optional: `pip install "chaincraft[ed25519]"`. The npm package is
`@chaincraft/core`. The unscoped name `chaincraft` on npm belongs to another
project.

## Hello World

These assume the packages above are installed. They open real TCP sockets.

### Two local nodes

Save as `hello.py` and run `python3 hello.py`. Node A listens on `9735`, node B
on `9736`, B dials A, then B gossips `app.hello`. Both record the same payload
id.

```python
import time
from chaincraft.mesh import Mesh
from chaincraft.object import SharedObject


class Hello(SharedObject):
    def receive(self, message):
        print("Received:", message["message"])


hello = Hello()
a = Mesh(on_app=lambda t, d: hello.receive(d) if t == "app.hello" else None)
b = Mesh()
print("listening", a.start("127.0.0.1", 9735))
print("listening", b.start("127.0.0.1", 9736))
b.connect(a.listen_addr)
digest = b.broadcast("app.hello", {"message": "Hello, Chaincraft!"})
time.sleep(0.4)
print(digest)
print(a.ids())
a.close()
b.close()
```

Rust: `Mesh::bind`, `Mesh::connect`, `Mesh::broadcast` (`use chaincraft::mesh::Mesh`).
TypeScript: `new Mesh()`, `await mesh.start`, `await mesh.connect`, `mesh.broadcast`.
A prototype implements `receive` and attaches it to `on_app` / `onApp`. Peers may
miss a message. A memento is for a consensus object, not for a chat room.

### Three languages on one mesh

Python holds `9735`. Rust binds `9736`. TypeScript binds `9737`. The last two
dial Python.

```bash
# Terminal 1
python3 -m chaincraft.node

# Terminal 2
chaincraft-node 127.0.0.1:9736

# Terminal 3
chaincraft-ts-node 127.0.0.1:9737
```

On terminals 2 and 3:

```json
{"cmd":"connect","addr":"127.0.0.1:9735"}
```

On terminal 1:

```json
{"cmd":"send","type":"app.hello","data":{"message":"Hello, Chaincraft!"}}
```

`sent.id` is SHA-256 of the canonical payload. After `ctl.hello`, the other
nodes print `received` with that same id. `{"cmd":"ids"}` lists it on every
node. `{"cmd":"quit"}` stops a process.

### More nodes, local or LAN

Start further processes on unused ports and `connect` them to a node that is
already listening. One mesh process keeps at most 256 live peers.

`connect` allows loopback, RFC1918, public unicast IPv4, `localhost`,
`.local`, and ordinary DNS names. Unspecified (`0.0.0.0`), link-local,
multicast, and reserved addresses are refused.

The default bind is `0.0.0.0:9735`. On another host:

```bash
python3 -m chaincraft.node
# other host
python3 -m chaincraft.node 0.0.0.0:9736
# then: {"cmd":"connect","addr":"203.0.113.10:9735"}
```

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
