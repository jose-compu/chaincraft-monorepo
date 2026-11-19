---
name: chaincraft-1
description: >-
  Bootstraps Chaincraft 1.9.0 in Python, Rust, and TypeScript: install from
  the v1.9.0 tag, run mesh nodes, implement receive / Protocol /
  BaseSharedObject, assemble PoW PoS PoA PoET PBFT Avalanche chains and a LWW CRDT
  at feature parity. Use when starting work in this monorepo, writing a
  protocol or blockchain object,
  running chaincraft-node, or when the user mentions Chaincraft, @chaincraft/core,
  chaincraft.node, or parity.
---

# Chaincraft 1.9.0 — agent bootstrap

Read this, then root `AGENTS.md`. Spec is `SPEC/`. Do not copy one language into another.

Spec release **1.9.0**. Wire protocol `v` stays **1**. Packages: PyPI and crates.io `chaincraft` 1.9.0, npm `@chaincraft/core` 1.9.0. Unscoped npm `chaincraft` is another project.

## Install

From the clone root. Python 3.9+, Rust 1.74+, Node 20+.

```bash
git clone --branch v1.9.0 https://github.com/jose-compu/chaincraft-monorepo.git
cd chaincraft-monorepo
python3 -m pip install -e "./python[dev]"
cargo build --bin chaincraft-node --manifest-path rust/Cargo.toml
npm install --prefix typescript
```

Published installs: `pip install chaincraft`, `cargo add chaincraft`, `npm install @chaincraft/core`.

## Envelope (same bytes in all three)

```python
from chaincraft import Envelope, encode_frame
env = Envelope.build("app.counter", {"by": "alice", "delta": 1})
frame = encode_frame(env.to_bytes())
```

```rust
use chaincraft::{encode_frame, Envelope, JsonValue};
let env = Envelope::build("app.counter", JsonValue::object([
    ("by".into(), JsonValue::String("alice".into())),
    ("delta".into(), JsonValue::Number(1)),
]), None)?;
let frame = encode_frame(&env.to_bytes()?)?;
```

```ts
import { Envelope, encodeFrame } from "@chaincraft/core";
const env = Envelope.build("app.counter", { by: "alice", delta: 1 });
const frame = encodeFrame(env.toBytes());
```

`id` is `sha256(canonical_json(data))`. From a TypeScript checkout, import `./src/index.ts`. The browser entry is `@chaincraft/core/browser`. It fetches a PeerJS id and does not import the TCP mesh.

## Mesh nodes

Core CLI is connect / send / ids / quit. BitTorrent is a Mesh client, not the core node. Default listen is `0.0.0.0:9735`. TCP is the interop default.

```bash
python3 -m chaincraft.node
cargo run --bin chaincraft-node --manifest-path rust/Cargo.toml
npm run node --prefix typescript
```

```json
{"cmd":"connect","addr":"127.0.0.1:PORT"}
{"cmd":"send","type":"app.hello","data":{"message":"Hello, Chaincraft!"}}
{"cmd":"ids"}
{"cmd":"quit"}
```

`connect` accepts any address `parse_address` accepts. A bare `host:port` is TCP. `udp://host:port` dials the optional localhost UDP listener. `ctl.hello` lists `udp` only while that listener is open. A browser must not advertise `udp`. `wire.framing-udp` stays exempt on TypeScript.

BT: `python3 -m chaincraft.bt_node`, `chaincraft-bt-node`, `npm run bt-node`.

## Channels

`channel.hybrid` (`LinkMesh`) relays one gossip envelope across joined tcp, udp, webrtc, pipe, mailto, forum, and loop members. A hop that cannot hold the envelope bytes is skipped. `link.*` and `ctl.*` go to one member. `mailto` and `webrtc` stay in-memory. This release does not open SMTP, an ICE data channel, or a live HTTP forum.

A `webrtc` rest is a PeerJS id (`A-Za-z0-9_-`, 1–64). A 64-hex id still parses. Default broker: `https://dechess-org-peerjs.vercel.app`.

## Protocol object

A prototype implements `receive` only. Override `is_valid` (`accept` in Rust) to reject. Override `add_message` only for consensus / mementos. Gossip (`app.*`) is relayed. `link.*` stays on that peer. `ctl.*` is mesh hello.

Python — `from chaincraft.object import SharedObject`

```python
class Room(SharedObject):
    def __init__(self):
        self.lines = []
    def receive(self, message):
        self.lines.append(message["text"])
```

Rust — `impl Protocol for Room` (`ApplicationObject` is the full contract). TypeScript — `class Room extends BaseSharedObject`. Attach application handlers on `Mesh` via `on_app` / `onApp`, not by editing `node.py` / `node.rs` / `node.ts`.

## Blockchain path

Compose on the same mesh: `ProofOfWork` / `ProofOfStake` / `ProofOfAuthority` / `ProofOfElapsedTime` / `PBFT` / `Avalanche` + `BalanceLedger` or `UtxoLedger` + mempool + fees. `CrdtKv` is a last-write-wins store. Specs under `SPEC/features/consensus-*.md`, `protocol-crdt-kv.md`, `ledger-*.md`, `mempool-basic.md`, `fees-policy.md`.

## Layout

| Path | Role |
|---|---|
| `SPEC/wire-v1.md` | Level 0 wire |
| `SPEC/semantics-v1.md` | Level 1 objects |
| `SPEC/features.yaml` | Parity registry |
| `SPEC/features/channel-hybrid.md` | One mesh, hop caps, UDP listener |
| `SPEC/features/channel-peer.md` | PeerJS ids and the browser entry |
| `SPEC/features/consensus-avalanche.md` | Slush, Snowflake, Snowball |
| `SPEC/features/protocol-crdt-kv.md` | Last-write-wins key-value |
| `python/` | Reference, `chaincraft` |
| `rust/` | Crate `chaincraft` |
| `typescript/` | `@chaincraft/core` |
| `conformance/` | Vectors + live interop |

Language notes: `python/AGENTS.md`, `rust/AGENTS.md`, `typescript/AGENTS.md`.

## Checks

```bash
cd python && python3 -m pytest tests/ -v
cd rust && cargo test --all-features
cd typescript && npm test
python3 conformance/run_all.py
python3 conformance/runner/run_interop.py
python3 tools/parity_check.py --summary
```

Do not regenerate `conformance/vectors/` to make a test pass. A vector failure means the port is wrong unless it contradicts `SPEC/`.

## Rules

1. Spec wins. Never resolve ambiguity by reading another language's source.
2. Every feature exists in all three languages (14-day clock). `wire.framing-udp` is exempt on TypeScript.
3. Parity is behaviour, not syntax.
4. New feature: spec → vectors → one language → the other two → `SPEC/features.yaml` in the same PR.
5. Never commit on `main`. No AI/Cursor/Claude co-author trailers. No summary `.md` files for a change.
