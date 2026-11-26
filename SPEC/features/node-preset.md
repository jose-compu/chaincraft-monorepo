# node.preset

**Release:** 1.12.0

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
| `udp` | When true, binds UDP in Python and Rust; TypeScript rejects `true` |

## Return value

`listen_addr`, `state()`, `submit(message)`, `connect(addr)`, `close()`.
`submit` applies locally and broadcasts `app.<protocol>`. Transfer nodes also
expose `produce(time)`.

The core CLI remains `connect` / `send` / `ids` / `quit`. No new binary. The
browser entry does not start a TCP mesh.

`conformance/vectors/node-preset.json` pins the transfer config against a
hand-built chain and rejection of unknown protocol and unknown keys.