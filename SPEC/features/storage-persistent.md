# storage.persistent

**Release:** 1.1.0

Prototype content-addressed message store. It specifies the *semantics*
of persistence: keys, insertion order, capacity, dump and load.

This is not a filesystem and not a database engine. Opening files, fsync
and concurrent writers are out of scope. A conforming implementation MAY
hold the store in memory; `dump` is the image that would be written, and
`load` is the image that would be read on restart.

## Parameters

| Name | Default | Rule |
|---|---|---|
| `capacity` | 8 | Positive integer. Maximum retained entries. |

Construction with a non-positive capacity is rejected.

## Record

An entry is an `id` and a `body`.

`id` is 64 lowercase hex digits. `body` is a non-empty string (typically
a canonical envelope). Extra keys are ignored.

## Put

`put(id, body)`:

1. Reject (return false) if `id` is not 64 lowercase hex or `body` is
   empty.
2. If `id` is already stored, replace `body` and return false. Do **not**
   move it in insertion order. Replacing does not refresh eviction rank —
   the same rule as `wire.dedup` §7.2.
3. If at capacity, evict the oldest insertion first, then append.
4. Store the body. Return true.

## Get / remove

`get(id)` returns `{found, body}`. Missing or invalid ids are
`found=false` and `body=""`.

`remove(id)` discards that entry if present. Returns whether it was
present.

## Dump / load

`dump()` is exactly:

```json
{"entries":[{"body":"<string>","id":"<hex>"},...],"v":1}
```

`entries` is insertion order. Canonical JSON sorts object keys.

`load(snapshot)` replaces the store. It succeeds only when `v` is 1,
`entries` is an array, every element has a valid `id` and non-empty
`body`, ids are unique, and `len(entries) <= capacity`. On failure the
store is unchanged. On success, insertion order is the array order.

`conformance/vectors/storage-persistent.json` pins put, overwrite,
FIFO eviction, dump and a rejected load.
