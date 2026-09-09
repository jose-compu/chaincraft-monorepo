# ledger.utxo

Pedagogical UTXO ledger. It implements the Level 1 object contract
(`SPEC/semantics-v1.md` §2) and is applied through the ordinary pipeline.

This is not a chain or a signer. A conforming implementation accepts
well-formed spends, replaces consumed outputs, and burns fees. The fee
is structural: `sum(inputs) - sum(outputs)`.

## Parameters

| Name | Default | Rule |
|---|---|---|
| `allocations` | `alice:100` | Non-empty map of owner id → integer value. Ids are non-empty strings. Each value is an integer in `1..=2^53-1`. |

Construction with an empty map, an empty id, or a value outside that
range is rejected.

Genesis creates one unspent output per allocation. Owners are visited
in Unicode code-point order. The id of the output for owner `O` is the
string `genesis:` concatenated with `O`.

## Transaction id

Given a message, the transaction id is
`sha256_hex(canonical_json(body))` where `body` is exactly:

```json
{"fee":<int>,"inputs":["<id>",...],"outputs":[{"owner":"<string>","value":<int>},...]}
```

Canonical JSON sorts the object keys. Array order is preserved. Extra
message keys are ignored when hashing. A caller-supplied `id` field is
ignored.

The id of output `i` (0-based) is the transaction id, a colon, and the
decimal index with no leading zeros: `<txid>:0`, `<txid>:1`, …

## Message

```json
{"ledger":"utxo","fee":2,"inputs":["genesis:alice"],"outputs":[{"owner":"bob","value":70},{"owner":"alice","value":28}]}
```

`inputs` is a non-empty array of non-empty strings. `outputs` is an
array (empty is allowed: the whole input value is the fee). Each
output has a non-empty `owner` and an integer `value >= 1`. `fee` is
an integer `>= 0`.

## `is_valid`

False unless all hold:

- `message` is an object and `ledger` is exactly `utxo`
- `fee` is an integer (not a boolean) `>= 0`
- `inputs` is a non-empty array of non-empty strings with no duplicates
- every input id is currently unspent
- `outputs` is an array; each element is an object whose `owner` is a
  non-empty string and whose `value` is an integer `>= 1`
- `sum(input values) == sum(output values) + fee`

`is_valid` has no side effects.

## `add_message`

Remove every input from the store. Append each new output in message
order under its computed id. Add `fee` to `burned`.

## Snapshot

`utxos` in insertion order (genesis in code-point owner order, then
each accepted transaction's outputs in message order). Each entry is
`{id, owner, value}`. Also `burned` and `supply` (`sum(values)`,
equal to genesis supply minus `burned`).

`emit_state_memento()` returns
`normalize(merkle_digest({"burned":burned,"utxos":utxos,"v":1}), [])`.
`is_merkelized()` is true.

`conformance/vectors/ledger-utxo.json` pins a spend with change, a
chained spend of a created output, and the rejection cases.
