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

When no driver is bound, `canonical()` is the parent-linked chain ending at the
highest stored height.

## `accept_block`

Rejects (returns false, no state change) when any hold:

- `chain` is not exactly `transfer`
- the header fails the rules above
- a block with the same header id is already stored
- any transaction fails verification
- `tx_root` does not match the ordered transaction ids
- replaying genesis through the parent prefix and this block's transactions does
  not yield `state_root`
- the parent id is missing, wrong, or leaves a gap to genesis
- `authorize` fails when a driver is bound

Duplicate accepts of the same block id are rejected.

## `produce`

`produce(time, producer)` requires non-negative integer `time` and a non-empty
`producer`. It builds the next-height block from the mempool prefix, attaches a
driver-built `proof` when a driver is bound, and calls `accept_block`. Returns
`null` when acceptance fails; included mempool transactions are removed only on
success.

## Driver

The chain does not import a consensus module. A driver implements
`build_proof(block)`, `authorize(block, proof) -> bool`, and
`canonical() -> list[block id]`. `authorize` feeds the bound consensus object; it
returns true only when that object accepts the proof and any driver-specific
checks pass. `canonical()` returns chain block header ids in fork order.

`make_driver(consensus, **options)` selects a driver. Options and defaults
below match `conformance/vectors/chain-transfer.json`.

| Driver | Options | Notes |
|---|---|---|
| `pow` | `difficulty` default `1` | PoW `parent` is the mapped PoW parent id, not the chain parent string directly |
| `poa` | `authorities` default `["alice"]` | `proof.proposer` must equal `proposer_for(height, authorities)` |
| `pos` | — | `header.time` must equal `header.height`; `proof.slot` equals height |
| `pbft` | `replicas` optional | One synthetic view-0 quorum round per block |
| `poet` | `seed` default `chaincraft-poet-genesis` | Height `1` uses `seed`; later heights use the parent chain block id as PoET seed |
| `avalanche` | — | Fresh Snowball instance per height with `k=1`, `alpha=1`, `beta=1` |
| `beacon` | `name` default `alice`, `sk` required to produce | Pulse `height` is `header.height - 1`; `header.producer` must equal `name` |
| `pox` | — | Fixed seed, cycle length, and stackers (see below); producer must be the elected miner |
| `ouroboros` | — | Fixed nonce, epoch length, and stakeholder table (see below); `proof.slot` equals height |

Chain block `header.height` is the consensus height, slot, or transfer step index.
`proof.payload` is always the chain block id (`merkle_digest` of the header).

### Proof shapes

**pow** — `consensus.pow` block whose `payload` is the chain block id; `parent` is
the PoW parent mapped from the chain parent.

**poa** — PoA block fields `height`, `parent`, `payload`, `proposer`, with PoA
`parent` mapped from the chain parent.

**pos** — `payload`, `proposer`, and `slot` with `slot` equal to header height.

**pbft** — `value` (chain block id), `digest` (`merkle_digest(value)`),
`primary`, `prepares`, and `commits`.

**poet** — `author`, `payload` (chain block id), `wait`, and `proof`.

**avalanche** — `{"consensus":"avalanche","messages":[...]}`; acceptance requires
the Snowball `final` flag after applying the messages.

**beacon** — `consensus.beacon` pulse with `height`, `previous`, `pk`, `proof`,
`output`; pulse height is one less than chain height.

**pox** — `{"consensus":"pox","messages":[...]}`: bids for the height, then one
tenure whose `winner` is the elected miner; `header.producer` must match.

**ouroboros** — `consensus.ouroboros` block with `slot` equal to header height,
`payload` the chain block id, `parent` the mapped Ouroboros parent id, and valid
VRF fields for the leader.

### Pox and Ouroboros driver constants

Vectors pin these embedded tables (not constructor parameters):

**pox** — seed `0123456789abcdef` repeated four times; `cycle_length` `3`;
cycle-0 stackers `alice:100`, `bob:200`, `carol:50`. Test bids use
`btc_out` `5`/`6`/`4` for `alice`/`bob`/`carol` at each height.

**ouroboros** — nonce same 64-hex pattern as pox; `epoch_length` `2`;
stakeholders `alice` stake `100` and `bob` stake `1` with the signing keys used
in `conformance/vectors/consensus-ouroboros.json` driver replay.

## Snapshot

`state()` returns balances, nonces, canonical block ids, height, and tip.

`conformance/vectors/chain-transfer.json` pins two-block runs per consensus,
rejection cases, and PoW/PoA reorgs.