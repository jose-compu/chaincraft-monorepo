# consensus.pow

Pedagogical proof-of-work object. It implements the Level 1 contract
(`SPEC/semantics-v1.md` §2) and is applied through the ordinary pipeline.

This is not a miner daemon and not a networked chain. A conforming
implementation accepts well-formed blocks, stores every valid one, and
chooses a tip. Mining is a helper used to build vectors.

## Parameters

| Name | Default | Rule |
|---|---|---|
| `difficulty` | 2 | Positive integer `1..=64`. Number of leading `0` hex digits the block id MUST have. |

## Block id

Given a message object, the id is `sha256_hex(canonical_json(header))` where
`header` is exactly:

```json
{"height":<int>,"miner":"<string>","nonce":<int>,"parent":"<string>","payload":"<string>"}
```

Canonical JSON sorts the keys. Extra message keys are ignored when hashing.
The id is computed; a caller-supplied `id` field is ignored.

A block meets the work requirement when its id starts with `difficulty`
lowercase hex zeros.

## Message

```json
{"consensus":"pow","height":1,"miner":"alice","nonce":0,"parent":"","payload":"genesis-child"}
```

`parent` is the empty string for a height-1 block. Otherwise it is a 64-char
lowercase hex id already in the store. `nonce` is an integer `>= 0`.
`miner` and `payload` are non-empty strings.

## `is_valid`

False unless all hold:

- `message` is an object and `consensus` is exactly `pow`
- `height`, `nonce` are integers; `height >= 1`; `nonce >= 0`
- `miner`, `parent`, `payload` are strings; miner and payload are non-empty
- if `parent` is empty, `height` is 1; otherwise `parent` is stored and
  `height` equals that block's height plus one
- the computed id meets the work requirement
- the id is not already stored

## `add_message`

Store the block under its id. The **tip** is the stored block of greatest
`height`; ties break to the lowest id by code point.

## Snapshot

`height` of the tip (0 when empty), `tip` (empty string when empty),
`blocks` in insertion order.

`emit_state_memento()` returns `normalize(merkle_digest({"height":h,"tip":t,"v":1}), [])`.
`is_merkelized()` is true.

`conformance/vectors/consensus-pow.json` pins mining, rejection, and a
same-height fork resolved by id.
