# consensus.pos

**Release:** 1.5.0

Prototype proof-of-stake object. Weighted, deterministic proposer
selection. No tokens move; stake is a constructor parameter.

Implements the Level 1 object contract. Applied through the pipeline.

## Parameters

| Name | Default | Rule |
|---|---|---|
| `seed` | `chaincraft-pos-v1` | Non-empty string. Domain separator for the lottery. |
| `validators` | `alice:2`, `bob:1`, `carol:1` | Map of id → positive integer stake. Ids are non-empty strings. |

Construction with an empty set, a non-positive stake, or an empty id is
rejected.

## Proposer

For slot `s` (integer `>= 1`):

1. `digest = sha256_hex(canonical_json({"seed":"<seed>","slot":s}))`
2. `pick = int(digest, 16) % total_stake`
3. Walk validator ids sorted by code point. Accumulate stake. The first
   id whose cumulative stake is `> pick` is the proposer.

The same `(seed, validators, slot)` MUST yield the same proposer in every
language.

## Message

```json
{"consensus":"pos","payload":"block-1","proposer":"alice","slot":1}
```

`slot` is the next expected slot (`current + 1`; current starts at 0).
`proposer` MUST be the scheduled proposer. `payload` is a non-empty string.

## `is_valid`

False unless all hold:

- `consensus` is exactly `pos`
- `slot` is an integer equal to `current + 1`
- `proposer` and `payload` are non-empty strings
- `proposer` equals `proposer_for(slot)`

## `add_message`

Set `current = slot`. Set `last_proposer` to the proposer. Set `head` to
`merkle_digest({"payload":payload,"slot":slot,"v":1})`.

## Snapshot

`slot`, `last_proposer` (empty before the first accept), `head`.

`emit_state_memento()` returns `normalize(head, [])`.
`is_merkelized()` is true.

`conformance/vectors/consensus-pos.json` pins the lottery and a wrong-proposer
rejection.
