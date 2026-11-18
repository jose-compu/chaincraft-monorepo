# fees.policy

**Release:** 1.8.0

Prototype fee policy. It ranks candidates for a block, splits a fee
into burned and tip portions, estimates a clearing fee, and steps a
base fee.

This is not a mempool and not a ledger. Integer arithmetic only; no
floating point.

## Select

`select(candidates, limit)` returns at most `limit` transaction ids.

Each candidate is `{id, fee}`. `id` is a non-empty string. `fee` is an
integer `>= 0`. Malformed candidates are ignored. If the same `id`
appears twice, the first well-formed occurrence wins.

`limit` is an integer `>= 1`. Construction or a call with `limit < 1`
is rejected.

Order: greater `fee` first; ties break to the lowest `id` by Unicode
code point. Then take the first `limit` ids.

## Charge

`charge(fee, base)` with integers `fee >= 0` and `base >= 0`:

| Field | Value |
|---|---|
| `charged` | `fee` |
| `burned` | `min(fee, base)` |
| `tip` | `fee - burned` |

## Estimate

`estimate(fees)` is the median of a list of integers `>= 0`.

- empty list → `0`
- sort ascending
- odd length → the middle element
- even length → floor of the average of the two middle elements
  (`(a + b) // 2`)

## Next base fee

`next_base_fee(base, parent_count, target)` with integers
`base >= 0`, `parent_count >= 0`, `target >= 1`:

```
denom = target * 8
if parent_count >= target:
    next = base + base * (parent_count - target) / denom
else:
    next = base - base * (target - parent_count) / denom
if next < 1:
    next = 1
```

`/` is non-negative integer division (the operands of each `/` are
`>= 0`). The result is never less than 1.

`conformance/vectors/fees-policy.json` pins ranking, the burn split,
median estimates and the base-fee step.
