# consensus.pox

**Release:** 1.9.0

Pedagogical Proof of Transfer. A frozen cycle-0 stacker snapshot and sortition by
SHA-256 over bid fields and a fixed seed elect the miner for each height. It implements
the Level 1 contract (`SPEC/semantics-v1.md` §2) and is applied through the ordinary
pipeline.

This is not a Stacks node, not a Bitcoin client, and not probability-weighted burn.
`btc_out` and stack `amount` are recorded and hashed; they do not rank the winner except
as hash input. `add_message` ignores an optional `frontier_state` argument.

## Constructor

- `seed`: 64 lowercase hex characters, `[0-9a-f]{64}`.
- `cycle_length`: integer `>= 1`.
- `stackers`: non-empty list of `{locker, amount}`. `locker` is a non-empty string.
  `amount` is an integer `>= 1`. Lockers are distinct and case-sensitive. This list is the
  cycle-0 snapshot and cannot change later.

Invalid constructor arguments are rejected (Python `ValueError`, Rust `Result<Self, String>`,
TypeScript `RangeError`). Integers are in `0..=9007199254740991`. Booleans and floats are
not integers.

Reward cycle of height `h >= 1` is `(h - 1) // cycle_length`. Open height starts at `1` and
becomes tip height `+ 1` after each accepted tenure.

## Messages

`consensus` must be exactly `pox`. Extra keys are ignored. A caller-supplied `id` is ignored.
Ids use the existing `merkle_digest` helper (SHA-256 hex of canonical JSON).

### stack

```json
{"consensus":"pox","kind":"stack","locker":"alice","amount":10,"reward_cycle":1}
```

Id is the digest of `{"amount","kind":"stack","locker","reward_cycle"}`.

Valid only when `reward_cycle` is an integer `>= 1`, `reward_cycle` is strictly greater than
the cycle of the open height, `locker` is a non-empty string, `amount` is an integer `>= 1`,
and that locker is not already stacked for that cycle. Cycle 0 cannot be stacked. Once the
open height enters cycle N, stacks for cycle N are rejected. Stacks for a later cycle are
still accepted.

### bid

```json
{"consensus":"pox","kind":"bid","miner":"alice","btc_out":5,"block_height":1}
```

Id is the digest of `{"block_height","btc_out","kind":"bid","miner"}`.

Valid only when `block_height` equals the open height, `miner` is a locker in
`snapshot(cycle(block_height))`, `btc_out` is an integer `>= 1`, and that miner has no bid
yet at that height.

Sortition score is the digest of `{"block_height","btc_out","miner","seed"}` with the object
seed. Among stored bids at that height, the winner is the lowest score in code-point order.
Equal scores break to the lowest bid id (`SPEC/semantics-v1.md` §6).

`snapshot(0)` is the constructor list. `snapshot(N)` for `N >= 1` is the accepted stack
messages for cycle N, in insertion order. An empty snapshot rejects every bid.

### tenure

```json
{"consensus":"pox","kind":"tenure","winner":"alice","prev":"","block_height":1}
```

Id is the digest of `{"block_height","kind":"tenure","prev","winner"}`.

Valid only when `block_height` equals the open height, at least one bid is stored for that
height, `winner` is the elected miner, `prev` is `""` when `block_height` is `1`, and
otherwise `prev` is the tip tenure id.

Accepting a tenure appends its id, advances the tip, and advances the open height. A second
tenure at the same height fails because the open height has moved. A later bid for the
closed height fails the same way.

## Accept, reject, snapshot

Invalid `add_message` stores nothing and returns the current memento.

`is_merkelized()` is true. `emit_state_memento()` is `normalize(merkle_digest({"height": h, "tip": tip, "v": 1}), [])`, with `height` `0` and `tip` `""` when empty. `get_state_digests()` is `[tip]` or `[]`.

`canonical` walks `prev` from the tip back to `""`, then reverses, same as PoA.

`state()`:

```json
{"height":0,"tip":"","open_height":1,"cycle":0,"canonical":[],"tenures":[],"bids":[],"stacks":[]}
```

`height` and `tip` describe the latest tenure. `cycle` is the cycle of `open_height`. The
three id lists are insertion order.

`conformance/vectors/consensus-pox.json` pins tenure acceptance, sortition, stack cycles,
bid rules, and rejection cases.