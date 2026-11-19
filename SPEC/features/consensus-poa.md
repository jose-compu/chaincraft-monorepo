# consensus.poa

**Release:** 1.9.0

Prototype proof-of-authority object. A fixed authority list rotates by block
height. Only the authority for that height may propose. It implements the Level
1 contract (`SPEC/semantics-v1.md` §2) and is applied through the ordinary
pipeline.

This is not a networked chain. A conforming implementation accepts well-formed
blocks, stores every valid one, and chooses a tip.

## Parameters

| Name | Rule |
|---|---|
| `authorities` | Non-empty list of distinct non-empty strings. Order is rotation order. Comparison is case-sensitive. |

Reject an empty list, a duplicate authority, or an empty string. One authority
is valid (that authority proposes every height).

## Turn

For height `h >= 1` and `n = len(authorities)`, the proposer is
`authorities[(h - 1) % n]`.

With `["alice","bob","carol"]`: height 1 → alice, 2 → bob, 3 → carol, 4 → alice.

## Block id

Given a message object, the id is `sha256_hex(canonical_json(header))` where
`header` is exactly:

```json
{"height":<int>,"parent":"<string>","payload":"<string>","proposer":"<string>"}
```

Canonical JSON sorts the keys. Extra message keys are ignored when hashing.
The id is computed; a caller-supplied `id` field is ignored.

## Message

```json
{"consensus":"poa","height":1,"parent":"","payload":"one","proposer":"alice"}
```

`parent` is the empty string for a height-1 block. Otherwise it is the id of a
stored block with height `h - 1`. `payload` and `proposer` are non-empty
strings.

## `is_valid`

False unless all hold:

- `message` is an object and `consensus` is exactly `poa`
- `height` is an integer `>= 1` (booleans are not integers)
- `proposer`, `parent`, `payload` are strings; `proposer` and `payload` are
  non-empty
- `proposer` equals the authority for that height
- if `parent` is empty, `height` is 1; otherwise `parent` is stored and
  `height` equals that block's height plus one
- the computed id is not already stored

Invalid input leaves state unchanged. `add_message` on invalid input stores
nothing and returns the current memento.

## `add_message`

Store the block under its id in insertion order. The **tip** is the stored
block of greatest `height`; ties break to the lowest id by code point.

Two payloads from the same authority at the same height are both valid (two
ids); the lower id is tip.

## Snapshot

`height` of the tip (0 when empty), `tip` (empty string when empty),
`blocks` in insertion order, and `canonical`.

`canonical` walks `parent` from the tip until the parent is empty, then
reverses. Authorities are not part of `state()`.

`emit_state_memento()` returns `normalize(merkle_digest({"height":h,"tip":t,"v":1}), [])`.
`is_merkelized()` is true. `get_state_digests()` returns `[tip]` or `[]` when
there is no tip.

## Reorg

Extending the current tip is not a reorg. A reorg is an accept whose new
`canonical` does not contain the previous tip.

`reorg_depth` is the number of blocks on the previous canonical chain that are
absent from the new one (the dropped suffix after the common prefix). It is 0
when the step is not a reorg.

`conformance/vectors/consensus-poa.json` pins rotation, rejection, a same-height
fork resolved by id, and a multi-block reorg with extension back to the prior
chain.