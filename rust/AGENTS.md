# AGENTS.md — Rust implementation

Read the root `AGENTS.md` first. This file covers only what is specific to `rust/`.

**Status: Level 0, Level 1, and Level 2 crypto (`ecdsa`/`vdf`/`vrf`) complete.** Stage 8 in `ROADMAP.md`.

## Role

A rewrite of the transport layer against `SPEC/wire-v1.md`, not a port of the previous
`chaincraft-rust` crate. Four things changed, all breaking:

| Area | Previous crate | Required by wire v1 |
|---|---|---|
| Transport | UDP only | TCP with a u32 length prefix; UDP optional |
| Serialization | `serde_json::to_string` on a struct | Canonical JSON, sorted keys, no floats |
| Message id | Hash over envelope fields | `sha256(canonical_json(data))` — payload only |
| Control messages | Ad hoc variants | The `ctl.*` namespace, §5 |

The application object model is the Level 1 contract in `SPEC/semantics-v1.md`.

Write from `SPEC/`. If the document is incomplete, fix the document and add a vector.

## Layout

```
src/
  canonical.rs   Canonical JSON encoder and parser (wire-v1 §1, §2)
  envelope.rs    Envelope (§3)
  framing.rs     TCP framing and UDP datagrams (§4)
  control.rs     ctl.* messages (§5)
  crypto.rs      BIP-340 Schnorr, Ed25519 (§6)
  ecdsa.rs       secp256k1 ECDSA (crypto-ecdsa.md)
  vdf.rs         Sloth VDF (crypto-vdf.md)
  vrf.rs         Deterministic ECDSA VRF (crypto-vrf.md)
  discovery.rs   Address book and local-discovery policy
  consensus_pow.rs   Prototype PoW object
  consensus_pos.rs   Prototype PoS object
  consensus_pbft.rs  Prototype PBFT object
  ledger_balance.rs  Prototype account ledger
  ledger_utxo.rs     Prototype UTXO ledger
  mempool.rs     Prototype transaction pool
  fees.rs        Prototype fee policy
  storage.rs     Prototype message store
  cli.rs         JSON-lines node command surface
  bittorrent.rs  Prototype BitTorrent swarm + client
  nat.rs         STUN, hole punch, and app.nat relay
  channel.rs     Address URIs and in-process loop channel
  pubsub.rs      Topic publish-subscribe (chat rooms)
  stream.rs      Append-only event log (producer lanes, range read)
  mesh.rs        TCP mesh (listen, hello, dedup, relay)
  dedup.rs       Seen-digest set and relay gate (§7)
  memento.rs     StateMemento (semantics-v1 §4)
  object.rs      ApplicationObject contract, digests, tie-break (§2, §5, §6)
  pipeline.rs    ObjectRegistry, validate-all-then-apply (§3)
  error.rs       Error classes
  features.rs    Feature manifest
  bin/features.rs  Prints the manifest as JSON
  bin/node.rs      Wire CLI: connect / send / ids / quit
  bin/bt_node.rs   BitTorrent client on Mesh (`bt.*` commands)
tests/
  conformance.rs Shared vectors from conformance/vectors/
  stream_perf.rs app.stream apply and read throughput
  pipe_perf.rs   channel.pipe mesh throughput
```

## Commands

```bash
cargo test --all-features --verbose
cargo run --quiet --bin features    # feature manifest, JSON on stdout
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
```

## Conventions

- Fallible operations return `Result<T, Error>`. Parity is of error *class*, not of
  message text: `Error::Protocol` where Python raises `ProtocolError` is correct.
- Object keys live in a `BTreeMap`. UTF-8 byte order is code point order, so the default
  sort is already the one §1.1 requires. Do not switch to a hash map.
- The crate carries its own JSON parser. `serde_json` would accept duplicate keys (it
  keeps the last) and is therefore not used on the receive path.
- Signature verification returns `bool` and never a `Result`. Malformed input is `false`.
- Clippy runs with `-D warnings`.
- The object trait is named `ApplicationObject`. Python and TypeScript call it
  `SharedObject`. A prototype implements `Protocol` and `receive`. Consensus
  objects implement `ApplicationObject` and return a memento.

## Crypto backend

`k256` (BIP-340 Schnorr and ECDSA), `ed25519-dalek` (RFC 8032), and `num-bigint`
(Sloth VDF). Verification must return `false` on malformed input rather than
propagating a library error.

## The feature manifest

`cargo run --quiet --bin features` must print JSON on stdout in exactly this shape,
because `tools/parity_check.py` parses it:

```json
{
  "impl": "rust-chaincraft/1.0.0",
  "language": "rust",
  "version": "1.0.0",
  "wire_version": 1,
  "features": ["wire.canonical-json", "wire.envelope"]
}
```

Nothing else may be written to stdout. Send diagnostics to stderr.
