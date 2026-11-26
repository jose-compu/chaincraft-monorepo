# chain.transfer

**Release:** 1.12.1

Pedagogical account chain: signed transfers, a chain-local fee-ordered
mempool, block headers with state and transaction roots, and fork choice
delegated to a consensus driver. This is not `ledger.balance`; fees credit the
block producer (plus an optional `reward`), not a burn counter.

Integers are in `0..=2^53-1`. Booleans and floats are not integers. Digests are
`merkle_digest` (SHA-256 hex of canonical JSON).

## Parameters

| Name | Default | Rule |
|---|---|---|
| `genesis` | — | Non-empty map of account id → balance `1..=2^53-1` |
| `reward` | `0` | Non-negative integer credited to the producer per block |

## Transaction body

Signature excluded from the body digest:

```json
{"amount":10,"fee":2,"nonce":0,"recipient":"bob","sender":"<64 lowercase hex>"}
```

`amount >= 1`, `fee >= 0`, `nonce >= 0`. `sender` is the BIP-340 x-only public
key. `recipient` is a non-empty string.

Transaction id is `merkle_digest` of the body. The signed message is the raw
32-byte SHA-256 of the canonical body. Algorithm is `schnorr` only.
`signature` is 128 lowercase hex.

## Signed transaction

The body fields plus `signature` (128 hex). Verification uses the existing
crypto module.

## Genesis state

Balances and nonces `0` for every genesis account.

## Apply transfer

Nonce must equal the sender's current nonce (unknown account: `0`). Debit
`amount + fee` from the sender. Credit `amount` to the recipient. Credit
`fee + reward` to the block producer (create if needed). Reject when the
sender balance is below `amount + fee`, or recipient or producer balance would
exceed `2^53-1`. Self-transfer debits the fee; when sender equals producer the
fee is credited back.

## Mempool

Chain-local. Order: fee descending, then transaction id ascending by code
point. `produce` takes a prefix of that order that applies cleanly and stops at
the first failure. Included ids leave the pool.

## Block header

```json
{"height":1,"parent":"","producer":"alice","state_root":"<64 hex>","time":1,"tx_root":"<64 hex>"}
```

`height >= 1`. `parent` is `""` at height 1, else parent block id. `time >= 0`
(caller-supplied). `tx_root` is `merkle_digest` of the ordered transaction-id
list (`[]` when empty). `state_root` is `merkle_digest` of
`{"balances","nonces","v":1}` after apply. Block id is `merkle_digest` of the
header.

## Block message

```json
{"chain":"transfer","header":{...},"transactions":[...],"proof":{...}}
```

`proof` shape depends on the consensus driver.

## Fork choice

Every valid block is stored. The canonical chain is whatever the driver returns.
State is genesis replay along that list. `import_blocks` replays a foreign list
from genesis.

## Driver

The chain does not import a consensus module. A driver implements
`authorize(block, proof) -> bool` and `canonical() -> list[block id]`.
`authorize` feeds the bound consensus object; it returns true only when that
object has accepted the block proof.

Adapters for `consensus.pow`, `consensus.poa`, `consensus.pos`,
`consensus.pbft`, `consensus.poet`, `consensus.avalanche`, `consensus.beacon`,
`consensus.pox`, and `consensus.ouroboros` are defined in the implementation
and pinned by `conformance/vectors/chain-transfer.json`.

## Snapshot

`state()` returns balances, nonces, canonical block ids, height, and tip.

`conformance/vectors/chain-transfer.json` pins two-block runs per consensus,
rejection cases, and PoW/PoA reorgs.