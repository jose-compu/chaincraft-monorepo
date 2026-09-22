# mempool.basic

**Release:** 1.0.0

Prototype transaction pool. It governs admission and retention: size,
minimum fee, per-sender cap, time-to-live and replace-by-fee.

This is not a block producer and not a ledger. Selection of which
pending transactions enter a block is `fees.policy`. Connecting to a
network is out of scope.

All times are millisecond Unix timestamps, injected by the caller. The
wall clock MUST NOT be read inside the pool.

## Parameters

| Name | Default | Rule |
|---|---|---|
| `capacity` | 8 | Positive integer. Maximum retained transactions. |
| `min_fee` | 0 | Integer `>= 0`. Floor for admission. |
| `ttl_ms` | 60000 | Integer `>= 0`. `0` disables expiry. |
| `max_per_sender` | 0 | Integer `>= 0`. `0` means no per-sender cap. |
| `rbf_min_increase` | 1 | Integer `>= 1`. Minimum fee increase to replace. |

Construction outside those ranges is rejected.

## Transaction

```json
{"fee":5,"nonce":0,"payload":"p","sender":"alice"}
```

`sender` and `payload` are non-empty strings. `fee` and `nonce` are
integers (not booleans); `fee >= 0`; `nonce >= 0`. Extra keys are
ignored.

The id is `sha256_hex(canonical_json({"fee":fee,"nonce":nonce,"payload":payload,"sender":sender}))`.
A caller-supplied `id` is ignored.

## Insert

`insert(tx, now_ms)`:

1. Sweep expired entries at `now_ms`.
2. Reject if the transaction is malformed, its id is already stored, or
   `fee < min_fee`.
3. If another entry has the same `(sender, nonce)`:
   - reject unless `fee >= existing.fee + rbf_min_increase`
   - otherwise discard the existing entry (this is a replacement, not an
     eviction) and continue
4. If this is not a replacement, `max_per_sender > 0`, and the sender
   already has that many entries, reject.
5. If at capacity:
   - the victim is the stored entry of least `fee`; ties break to the
     earliest insertion
   - reject if `fee <= victim.fee`
   - otherwise discard the victim (eviction) and continue
6. Store the transaction at the end of insertion order with
   `received_at = now_ms`.

Replacement and eviction give the new entry a fresh insertion rank.

## Remove

`remove(id)` discards that entry if present. Returns whether it was
present.

## Expire

`sweep(now_ms)` removes every entry with `now_ms - received_at > ttl_ms`
when `ttl_ms > 0`. An entry whose `received_at` is in the future is
kept. If `ttl_ms` is 0, nothing is removed. Return the number removed.

## Snapshot

`ids` in insertion order. `size` is the length of that list.

`conformance/vectors/mempool-basic.json` pins admission, replace-by-fee,
lowest-fee eviction and TTL.
