# storage.index

**Release:** 1.7.0

Optional local equality index on chosen payload fields inside stored
message bodies. It sits on `storage.persistent` and does not change
put, get, dump, or wire behaviour.

The store body remains an opaque string. When the body is a canonical
envelope whose `type` was registered and whose `data` contains a
top-level field name (no dotted paths), that field may contribute index
keys.

## Registration

`register(type, field)` must run before `put` indexes that pair.

- `type` matches envelope `type` (wire-v1 §3).
- `field` is 1–64 characters from `A–Z`, `a–z`, `0–9`, `.`, `_`, `-`.
- At most **8** distinct `(type, field)` pairs. A repeat is a no-op and
  returns true. A ninth distinct pair is rejected (returns false).
- Invalid `type` or `field` is rejected (returns false).

## Indexed values

Given a registered `(type, field)`, after each `put` the implementation
parses the body when possible. If parsing succeeds, `type` matches,
and `data[field]` is present:

| `data[field]` | Indexed |
|---|---|
| string | yes, as that string |
| integer in the wire safe range, not a boolean | yes |
| boolean | yes |
| array | each **top-level** element that is a string, wire-safe integer, or boolean; nested arrays, objects, null, and floats are skipped |
| object, null, float, boolean mistaken for integer | no |

`put` is never rejected because the body does not index. Failed or
non-envelope bodies are stored unchanged with no index update beyond
eviction rules.

Equality is exact: boolean `true` does not match integer `1`. Duplicate
array elements add the message id **once** per put.

## Query

`query(type, field, value)` returns message ids in **store insertion
order** whose indexed field equals `value` (same type and value). If
`(type, field)` was never registered, return an empty list.

## Lifecycle

- **Overwrite** (`put` on an existing id): replace indexed keys for that
  id; insertion rank is unchanged (`storage.persistent` § Put).
- **Eviction** and **`remove`**: drop that id from every index.
- **`dump`**: unchanged `{entries, v:1}`; registrations are not serialized.
- **`load`**: on success, rebuild the entire index by walking `entries`
  in array order. On failure, leave the store and index unchanged.

`conformance/vectors/storage-index.json` pins register, put, query,
overwrite order, eviction, remove, load, and non-indexed payloads.