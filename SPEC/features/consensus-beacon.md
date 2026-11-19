# consensus.beacon

**Release:** 1.9.0

Chained VRF randomness beacon. Each pulse proves unpredictable output at a height
that cites the previous output. It implements the Level 1 contract
(`SPEC/semantics-v1.md` §2) and is applied through the ordinary pipeline.

This is a single linear chain. The first valid pulse at the next height stays; a
later pulse at that height is rejected. There is no fork choice, no reorg, no wall
clock, and `add_message` ignores an optional `frontier_state` argument.

## Pulse

```json
{
  "consensus": "beacon",
  "height": 0,
  "previous": "<64 lowercase hex>",
  "pk": "<66 lowercase hex>",
  "proof": "<128 lowercase hex>",
  "output": "<64 lowercase hex>"
}
```

Extra keys are ignored and are not part of the id. A caller-supplied `id` is ignored.

## VRF message

UTF-8 bytes of `canonical_json({"height": <int>, "previous": "<64 lowercase hex>"})`.
`proof`, `output`, and `pk` come from `crypto.vrf` `evaluate(message, sk)`. Verification is
`vrf.verify(message, proof, pk, output)`. Implementations must not reimplement the output
formula.

## Pulse id

`sha256_hex(canonical_json({"height","output","pk","previous","proof"}))`, using the same
helper as the PoET ticket id.

## Genesis previous

When the chain is empty, the expected `previous` is 64 ASCII `0` characters (not `0x`).

## `is_valid`

False (no state change) unless all hold:

- `message` is an object and `consensus` is exactly `beacon`
- `height` is an integer in `0..=9007199254740991` (booleans and floats are not integers)
- `previous` is 64 characters matching `[0-9a-f]`; `pk` is 66; `proof` is 128; `output` is 64
  (uppercase, `0x` prefix, or wrong length fail)
- if the chain is empty: `height` is `0` and `previous` is the genesis previous
- if a tip exists: `height` is `tip_height + 1` and `previous` equals the tip `output`
- `vrf.verify` on the VRF message is true for the given `proof`, `pk`, and `output`
- the computed id is not already stored

## Accept

Append the pulse id. `canonical` and `pulses` are the same list in insertion order.

## Snapshot

Empty state: `{"canonical":[],"height":-1,"output":"","pulses":[]}`.

After at least one pulse, `height` is the tip height and `output` is the tip output hex.

`emit_state_memento()` is `normalize(merkle_digest({"height": h, "output": output, "v": 1}), [])`
with `height` `-1` and `output` `""` when empty.

`is_merkelized()` is true. `get_state_digests()` is `[tip_id]`, or `[]` when empty.

Invalid `add_message` returns the current memento unchanged.

`conformance/vectors/consensus-beacon.json` pins chained acceptance, height and previous
rules, VRF failures, duplicate rejection, and malformed pulses.