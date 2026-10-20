# consensus.pbft

**Release:** 1.3.0

Prototype Castro–Liskov three-phase object (pre-prepare / prepare /
commit). One replica's log, driven by messages — it does not broadcast.

View changes and timeouts are out of scope.

## Parameters

| Name | Default | Rule |
|---|---|---|
| `replicas` | `r0`, `r1`, `r2`, `r3` | Unique non-empty ids, stored sorted by code point. `N >= 1`. |

`f = (N - 1) // 3`. Quorum `q = 2f + 1`. Primary for view `v` is
`replicas[v % N]`.

## Message

```json
{"consensus":"pbft","digest":"<64 hex>","phase":"pre-prepare","replica":"r0","sequence":1,"value":"hello","view":0}
```

`phase` is `pre-prepare`, `prepare`, or `commit`.
`view` and `sequence` are integers; `view >= 0`; `sequence >= 1`.
`replica` is a member of the set.
`digest` is 64 lowercase hex chars.

On `pre-prepare`, `value` is a string and
`digest == sha256_hex(canonical_json(value))`. The `replica` field MUST be
the primary for `view`. Prepare and commit MUST NOT be required to carry
`value`.

## `is_valid`

False on a structural or primary/digest violation. A well-formed message
for a different view or sequence is still valid: `add_message` ignores it.
That keeps an out-of-order vote from failing the whole pipeline.

## `add_message`

Operate only when `view` and `sequence` match the object's current pair
(initially `0`, `1`):

1. **pre-prepare.** If none stored for this pair, store `(digest, value)`.
   A second pre-prepare is ignored.
2. **prepare / commit.** Ignored until a pre-prepare is stored. Ignored
   when `digest` does not match it. The first vote per replica is kept;
   later votes from the same replica are ignored.
3. **execute.** When both prepare and commit have at least `q` votes for
   the stored digest, append `{seq, digest}` to `executed`, increment
   `sequence`, and clear the current pair's votes and pre-prepare.

## Snapshot

`view`, `sequence`, `prepares` (count for the current digest, else 0),
`commits` (same), `executed` (list of `{digest, seq}` in execution order).

`emit_state_memento()` returns
`normalize(merkle_digest({"executed":[...digests],"sequence":s,"v":1}), [])`.
`is_merkelized()` is true.

`conformance/vectors/consensus-pbft.json` pins a full quorum path and
ignored out-of-sequence votes.
