# consensus.ouroboros

**Release:** 1.12.1

Pedagogical Cardano Ouroboros–shaped slot lottery. Each slot, stakeholders
produce a VRF proof over the epoch nonce; stake-weighted threshold election picks
leaders; the longest slot chain is canonical with lowest block id on ties.
Implements the Level 1 contract (`SPEC/semantics-v1.md` §2). `add_message`
ignores an optional `frontier_state` argument.

This is not a Cardano node: no KES, no relative time, no stake delegation.

## Constructor

- `nonce`: 64 lowercase hex characters, `[0-9a-f]{64}`.
- `epoch_length`: integer `>= 1`.
- `stakeholders`: non-empty list. Each entry has `id` (non-empty string,
  case-sensitive, distinct), `stake` (integer `>= 1`), and `pk` (66 lowercase
  hex, compressed secp256k1 public key).

Invalid constructor arguments are rejected (Python `ValueError`, Rust
`Result<Self, String>`, TypeScript `RangeError`). Integers are in
`0..=9007199254740991`. Booleans and floats are not integers. The sum of
stakes must not exceed the safe-integer maximum.

`epoch_of(slot, epoch_length) = (slot - 1) // epoch_length`.

## Block

```json
{"consensus":"ouroboros","slot":1,"parent":"","payload":"one","leader":"alice","pk":"<66 hex>","proof":"<128 hex>","output":"<64 hex>"}
```

Block id is `merkle_digest({"leader","output","parent","payload","pk","proof","slot"})`.
Extra keys are ignored. A caller-supplied `id` is ignored.

### Validation

`is_valid` is false unless all hold:

- `consensus` is exactly `ouroboros`
- `slot` is an integer `>= 1` within the safe range
- `leader`, `parent`, and `payload` are strings; `leader` and `payload` are non-empty
- `pk`, `proof`, and `output` are lowercase hex of 33, 64, and 32 bytes
- `leader` is a stakeholder and `pk` matches that stakeholder's registered key
- slot 1 has `parent` `""`; otherwise `parent` is a stored block whose slot is exactly `slot - 1`
- Epoch nonce for the VRF message: epoch 0 uses the constructor nonce; the first
  slot of a later epoch uses the parent's `output`; any later slot in that epoch
  uses the epoch nonce stored on the parent block
- VRF message is UTF-8 bytes of
  `canonical_json({"epoch": <int>, "nonce": "<64 hex>", "slot": <int>, "stakeholder": "<id>"})`
- `vrf.verify` succeeds and `eligible(output, stake, total)` is true
- the computed id is not already stored

`eligible`: interpret the 32-byte VRF output as big-endian unsigned integer `O`.
True iff `O * total < stake * 2^256` using integer arithmetic. A sole stakeholder
is always eligible.

Several stakeholders may pass the threshold in one slot; each block is stored.
The same leader may submit two payloads at one slot (VRF omits `payload`).

## Chain rule

Tip is the stored block with the greatest `slot`. Equal `slot` breaks to the
lowest block id in code-point order. `canonical` walks `parent` from tip to `""`
and reverses.

A reorg is an accept whose new `canonical` does not contain the previous tip.
`reorg_depth` is the number of blocks on the old canonical chain missing from the
new one, otherwise 0.

## State

```json
{"slot":0,"tip":"","canonical":[],"blocks":[],"epoch":0,"nonce":"<constructor nonce>"}
```

`slot` is the tip slot, or 0 when empty. `epoch` and `nonce` describe the next
slot (`tip + 1`, or slot 1 when empty). `blocks` is insertion order.

`emit_state_memento()` is `normalize(merkle_digest({"nonce","slot","tip","v":1}), [])`.
`is_merkelized()` is true. `get_state_digests()` is `[tip]`, or `[]` when empty.

A contiguous chain cannot skip a slot.