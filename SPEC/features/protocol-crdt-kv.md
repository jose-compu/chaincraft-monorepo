# protocol.crdt-kv

**Release:** 1.12.2

Last-write-wins key-value store. Each key is one register. Merge is
deterministic. There is no wall clock: `ts` is an integer the caller
injects.

This is not an OR-set, not a filesystem, and not a networked replica
daemon. A Mesh client MAY gossip the messages; the core node binaries
stay wire-only.

The object implements the Level 1 contract (`SPEC/semantics-v1.md` §2).
It is not merkelized. A missing replica is a gap, not a fork.

## Limits

| Name | Value |
|---|---|
| `MAX_KEYS` | 32 |
| `MAX_VALUE` | 256 Unicode scalar values |
| name | 1 to 64 characters in `A–Z`, `a–z`, `0–9`, `.`, `_`, `-` |

A name is a `key` or a `writer`. The empty string is rejected.

## Messages

```json
{"app":"crdt","key":"x","op":"set","ts":1,"value":"hello","writer":"alice"}
{"app":"crdt","key":"x","op":"del","ts":2,"writer":"alice"}
```

`op` is exactly `set` or `del`. `ts` is an integer in `0..=2^53-1` and
is not a boolean. `set` requires `value` as a string of 1 to
`MAX_VALUE` characters. Extra keys are ignored.

## Winner

For one key, incoming beats stored when:

1. there is no stored register, or
2. `incoming.ts > stored.ts`, or
3. the timestamps are equal and `incoming.writer` is less than
   `stored.writer` by Unicode code point.

Equal timestamp and equal writer: the message is valid only when `op`
and `value` (empty for `del`) match the store. It is a no-op. A
different payload at the same `(key, ts, writer)` is rejected.

A `del` that wins stores a tombstone. A later `set` with a higher `ts`
restores the key.

A `set` that would create key number `MAX_KEYS + 1` is rejected. A
write to an existing key, including a tombstone, does not count as
create.

## Snapshot

`keys` sorted by key name. Each entry:

| Field | Rule |
|---|---|
| `deleted` | true for a tombstone |
| `key` | the name |
| `ts` | the winning timestamp |
| `value` | the string, or `""` when deleted |
| `writer` | the winning writer |

`conformance/vectors/protocol-crdt-kv.json` pins a set, a concurrent
tie, a tombstone, an idempotent replay, and a rejected stale write.
