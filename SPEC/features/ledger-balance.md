# ledger.balance

**Release:** 1.5.0

Prototype account-balance ledger. It implements the Level 1 object
contract (`SPEC/semantics-v1.md` §2) and is applied through the ordinary
pipeline.

This is not a chain, a mempool, or a fee market. A conforming
implementation accepts well-formed transfers, updates balances and
nonces, and burns fees. Overdraft is not permitted.

## Parameters

| Name | Default | Rule |
|---|---|---|
| `allocations` | `alice:100` | Non-empty map of account id → integer balance. Ids are non-empty strings. Each balance is an integer in `1..=2^53-1`. |

Construction with an empty map, an empty id, or a balance outside that
range is rejected.

## Accounts

An account is known if it appears in `allocations` or has been the
sender or recipient of an accepted transfer. Unknown accounts have
balance `0` and nonce `0` and are not reported in the snapshot until
they become known.

## Message

```json
{"ledger":"balance","sender":"alice","recipient":"bob","amount":10,"fee":2,"nonce":0}
```

`amount` is an integer `>= 1`. `fee` is an integer `>= 0`. `nonce` is an
integer `>= 0`. `sender` and `recipient` are non-empty strings.
Self-transfers are allowed: the sender is debited `amount + fee` and
credited `amount`, so the net effect is a fee burn.

Extra keys are ignored.

## `is_valid`

False unless all hold:

- `message` is an object and `ledger` is exactly `balance`
- `sender` and `recipient` are non-empty strings
- `amount`, `fee`, `nonce` are integers (not booleans); `amount >= 1`;
  `fee >= 0`; `nonce >= 0`
- `nonce` equals the sender's current nonce (0 if the sender is unknown)
- the sender's balance is `>= amount + fee`
- the recipient's resulting balance is `<= 2^53-1`

`is_valid` has no side effects.

## `add_message`

Debit `amount + fee` from the sender. Credit `amount` to the recipient
(creating the account if needed). Increment the sender's nonce by one.
Add `fee` to `burned`.

## Snapshot

`balances` and `nonces` for every known account, `burned`, and
`supply` (`sum(balances)`, equal to genesis supply minus `burned`).

`emit_state_memento()` returns
`normalize(merkle_digest({"balances":balances,"burned":burned,"nonces":nonces,"v":1}), [])`.
`is_merkelized()` is true.

`conformance/vectors/ledger-balance.json` pins a transfer, a nonce
sequence, a self-transfer, and the rejection cases.
