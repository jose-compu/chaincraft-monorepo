# AGENTS.md — Rust implementation

Read the root `AGENTS.md` first. This file covers only what is specific to `rust/`.

**Status: not yet implemented.** Stage 5 in `ROADMAP.md`.

## Migrating from `chaincraft-rust`

This is not a port of the existing crate; it is a rewrite of its transport layer against
`SPEC/wire-v1.md`. Four things change, and all four are breaking:

| Area | Existing crate | Required by wire v1 |
|---|---|---|
| Transport | UDP only | TCP with a u32 length prefix; UDP optional |
| Serialization | `serde_json::to_string` on a struct | Canonical JSON, sorted keys, no floats |
| Message id | Hash over envelope fields | `sha256(canonical_json(data))` — payload only |
| Control messages | Ad hoc variants | The `ctl.*` namespace, §5 |

The application object model largely survives; the wire layer does not.

## Planned layout

```
src/
  canonical.rs   Canonical JSON (wire-v1 §1)
  envelope.rs    Envelope (§3)
  framing.rs     TCP framing (§4)
  control.rs     ctl.* messages (§5)
  crypto.rs      BIP-340 Schnorr, Ed25519 (§6)
  features.rs    Feature manifest
  bin/features.rs  Prints the manifest as JSON
tests/
  conformance.rs Shared vectors from conformance/vectors/
```

## Commands

```bash
cargo test --all-features
cargo run --bin features        # feature manifest, JSON on stdout
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
```

## Conventions

- Fallible operations return `Result<T, ProtocolError>`. Parity is of error *class*, not
  of error type: Rust returning `Err(ProtocolError::…)` where Python raises
  `ProtocolError` is correct. Returning `Ok` where Python raises is a parity bug.
- `serde_json`'s default `Map` is a `BTreeMap`, so keys serialize sorted and UTF-8 byte
  order matches Python's code-point ordering. Do **not** enable the `preserve_order`
  feature — it silently breaks canonical output and every digest with it.
- Reject floats explicitly. `serde_json::Value::Number` accepts them; wire v1 does not.
- Signature verification returns `bool`, never a `Result`. Malformed input is `false`.
- Clippy runs with `-D warnings`.

## The feature manifest

`src/bin/features.rs` must print JSON on stdout in exactly this shape, because
`tools/parity_check.py` parses it:

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
