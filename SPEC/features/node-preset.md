# node.preset

**Release:** 1.12.2

One JSON configuration object, with the same keys in all three languages, that
starts a `chain.transfer` node on a mesh or constructs an existing protocol
object and attaches it.

## `start(config)`

Unknown keys are rejected. Keys that do not apply to the chosen protocol are
rejected. Invalid config raises `ValueError` / `RangeError` / `Result` error.

```json
{
  "protocol": "transfer",
  "consensus": "poa",
  "authorities": ["alice"],
  "genesis": {"alice": 100},
  "reward": 1,
  "listen": "127.0.0.1:0",
  "peers": [],
  "udp": false
}
```

| Key | Rule |
|---|---|
| `protocol` | `transfer`, `balance`, `utxo`, `crdt`, `pubsub`, or one of the nine consensus names |
| `consensus` | Required when `protocol` is `transfer` |
| `genesis` | Required when `protocol` is `transfer`; same rules as `chain.transfer` |
| `reward` | Optional non-negative integer for transfer |
| `authorities` | Required for `poa` transfer preset |
| `listen` | Default `127.0.0.1:0`, passed to mesh start |
| `peers` | List of addresses for `connect` |
| `udp` | When true, binds the optional UDP listener on Python, Rust, and TypeScript (Node). Default `false` |

When `protocol` is `transfer`, `authorities` is allowed only for `consensus`
`poa` and is required there (non-empty list).

When `protocol` is one of the nine consensus names (`pow` through `ouroboros`),
only `protocol`, `listen`, `peers`, and `udp` are always allowed. Additional
keys are rejected unless they configure that object:

| Protocol | Optional keys | Defaults |
|---|---|---|
| `pow` | `difficulty` | `2` for preset; transfer `make_driver` uses `1` |
| `poa` | `authorities` | `["alice"]` |
| `pbft` | `replicas` | implementation default replica set |
| `poet` | `seed` | `chaincraft-poet-genesis` |
| `pox` | `seed`, `cycle_length`, `stackers` | 64 ASCII `0` digits, `3`, `[{locker:"alice",amount:100}]` |
| `avalanche` | — | `slush` profile in the preset constructor |
| `beacon`, `pos`, `ouroboros` | — | constructor defaults from each feature spec |

For `balance` and `utxo`, `genesis` defaults to `{"alice": 100}` when omitted.

## Return value

`listen_addr`, `state()`, `submit(message)`, `connect(addr)`, `close()`.

`state()` returns the attached object's state document, with the same keys as
that object's `state()`. Transfer presets return the chain document
(`balances`, `nonces`, `canonical`, `height`, `tip`). Consensus and ledger
presets return their object's initial state; an empty object is not used in
place of a non-transfer object's state.

For consensus presets, optional keys in the table above are accepted when
present. An absent key keeps its default. A present key with the wrong JSON
type is rejected before the listen socket binds (`true` is not an integer).
PoX `stackers` are a non-empty list of `{locker, amount}` objects (`locker`
non-empty string, `amount` integer `>= 1`, distinct lockers). A
`[locker, amount]` pair is rejected.

Inbound mesh messages on `app.<protocol>` are applied when valid. `submit`
applies locally and broadcasts the same envelope type.

For `protocol` `transfer`, `submit` accepts a signed transaction or a full
`chain.transfer` block (`chain` field `transfer`); both paths broadcast
`app.transfer`. Transfer handles also expose `produce(time, producer)`; default
producer in the reference helper is `alice` when omitted.

The browser package entry does not expose `start`; TCP presets are Node and
Python/Rust CLI flows only.

The core CLI remains `connect` / `send` / `ids` / `quit`. No new binary. The
browser entry does not start a TCP mesh.

`conformance/vectors/node-preset.json` pins the transfer config against a
hand-built chain, rejection of unknown protocol and keys, preset `state()`
documents, and submit probes for PoA, PoX, and PoW difficulty.