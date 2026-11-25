# consensus.poet

**Release:** 1.10.0

Prototype Proof of Elapsed Time. Peers submit wait tickets backed by a Sloth
VDF proof over a shared seed. The shortest verified wait wins; an equal wait
breaks to the lowest ticket id. It implements the Level 1 contract
(`SPEC/semantics-v1.md` §2) and is applied through the ordinary pipeline.

This is not a networked chain and does not use wall-clock time or trusted
hardware. There is one round, not a block chain.

## Parameters

| Name | Rule |
|---|---|
| `seed` | Non-empty string at construction. UTF-8 bytes are the VDF input. Not part of `state()`. |

Reject an empty `seed` in the constructor.

## Ticket

```json
{"author":"alice","consensus":"poet","payload":"one","proof":"<hex>","wait":2}
```

`wait` is the Sloth iteration count `t` (`crypto.vdf`). `proof` is the canonical
lowercase hex from `proof_to_hex`. `author` and `payload` are non-empty
strings; they are not VDF inputs.

## Ticket id

`sha256_hex(canonical_json({"author","payload","proof","wait"}))`. Extra message
keys are ignored. A caller-supplied `id` is ignored.

## `is_valid`

False unless all hold:

- `message` is an object and `consensus` is exactly `poet`
- `wait` is an integer in `1..=4294967295` (booleans are not integers)
- `author` and `payload` are non-empty strings
- `proof` is a string equal to its canonical hex encoding (lowercase, no `0x`,
  no leading zeros except the value `0`)
- `vdf.verify(utf8(seed), wait, proof_int)` is true for the constructed seed
- the computed id is not already stored

Invalid input leaves state unchanged.

## Accept and winner

Store the ticket under its id in insertion order. The winner is the stored
ticket with the smallest `wait`. Ties go to the lowest id (code point order).

## Snapshot

`wait` is `0` and `winner` is `""` when empty. Otherwise `wait` is the winner's
wait, `winner` is its id, and `canonical` is a one-element list of that id.
`tickets` lists every accepted id in insertion order, including losers.

`emit_state_memento()` is `normalize(merkle_digest({"v":1,"wait":w,"winner":winner}), [])`.
`is_merkelized()` is true. `get_state_digests()` is `[winner]`, or `[]` when empty.

## Reorg

A reorg is an accept whose new `canonical` does not contain the previous winner.
`reorg_depth` is `len(previous canonical) - shared prefix`, and `0` when it is not
a reorg. Replacing the winner is depth 1. The first ticket is not a reorg.

`conformance/vectors/consensus-poet.json` pins shortest-wait replacement, equal-wait
tie-break, duplicate rejection, and invalid tickets.