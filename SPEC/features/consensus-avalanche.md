# consensus.avalanche

**Release:** 1.10.0

Pedagogical Slush, Snowflake, and Snowball. One object, a `phase`
discriminator. Sample outcomes are messages. There is no network, no
wall clock, and no PRNG.

This is not AvalancheGo, Snowman, or the DAG engine. Those remain
separate issues.

The object implements the Level 1 contract (`SPEC/semantics-v1.md` §2)
and is merkelized.

## Parameters

| Name | Default | Rule |
|---|---|---|
| `phase` | `snowball` | Exactly `slush`, `snowflake`, or `snowball`. |
| `k` | 2 | Sample size. Integer `1..=16`. |
| `alpha` | 2 | Quorum. Integer `1..=k` and `alpha > k/2`. |
| `beta` | 2 | Decision threshold. Integer `1..=16`. |

Construction that breaks those rules is rejected. `alpha > k/2` means a
round has at most one winning colour.

Colours are exactly `blue` and `red`.

## Messages

```json
{"color":"red","consensus":"avalanche","op":"init"}
{"consensus":"avalanche","op":"round","votes":["red","red"]}
```

`init` is valid only when `pref` is empty. `color` is `blue` or `red`.

`round` is valid only when `final` is false, `votes` is an array of
length `k`, and every entry is `blue` or `red`. Extra keys are ignored.

## `add_message`

`init` sets `pref` to `color`.

`round` increments `rounds`. Count the votes. If a colour `C` has at
least `alpha` votes, the round is a success for `C`. Otherwise it is a
failure.

**Slush.** Success sets `pref` to `C`. Failure changes nothing. Slush
never sets `final`.

**Snowflake.** Success: if `pref` is empty or equals `C`, set `pref` to
`C` and add 1 to `cnt`; otherwise set `pref` to `C` and `cnt` to 1.
Failure sets `cnt` to 0. `final` becomes true when `cnt >= beta`.

**Snowball.** Success: add 1 to `d[C]`. Set `pref` to `C` when `pref` is
empty, when `d[C] > d[pref]`, or when `d[C] == d[pref]` and `C` is less
than `pref` by Unicode code point (`blue` before `red`). Failure
changes no confidence. `final` becomes true when `d[pref] >= beta`.

## Snapshot

```json
{"cnt":0,"d":{"blue":0,"red":0},"final":false,"phase":"snowball","pref":"","rounds":0}
```

`d` always has both colours. `pref` is `""`, `blue`, or `red`.
`emit_state_memento()` is `normalize(merkle_digest({"state": snapshot, "v":1}), [])`.

`conformance/vectors/consensus-avalanche.json` pins one transcript per
phase, a rejected short vote array, and an init after `pref` is set.
