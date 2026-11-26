# bittorrent.swarm

**Release:** 1.12.0

Prototype BitTorrent swarm. It tracks one or more torrents: metainfo,
verified piece bytes, and which peers have which pieces.

This is not a tracker, a DHT, or a wire-protocol replica of BEP 3. Piece
exchange rides the ordinary Level 0 mesh as `app.bittorrent` envelopes
and is applied through the Level 1 object contract.

Prototype limits (a conforming implementation MUST reject construction
or a message that exceeds them):

| Cap | Value |
|---|---|
| torrents per swarm | 8 |
| pieces per torrent | 64 |
| piece bytes | 65536 |
| name / peer id | 64 UTF-8 bytes |
| distinct have-peers per torrent | 32 |

`split_payload` MUST reject a payload longer than `64 * 65536` bytes or
that would produce more than 64 pieces.

## Info hash

Given a torrent name and the list of piece hashes,

```
info_hash = merkle_digest({"name": <string>, "pieces": [<hex>, ...]})
```

Each piece hash is `sha256_hex` of the raw piece bytes. The payload of a
`piece` message is those bytes as lowercase hex (even length, at least
one byte).

## Message

Every message is an object with a `bt` discriminator. Extra keys are
ignored.

### `metainfo`

```json
{"bt":"metainfo","name":"demo","pieces":["<64 hex>", "..."]}
```

`name` is a non-empty string. `pieces` is a non-empty array of 64
lowercase hex strings.

Valid if the torrent is unknown, or already known with the same `name`
and `pieces`. `receive` creates the torrent when unknown; a matching
re-announce is a no-op.

### `have`

```json
{"bt":"have","info_hash":"<64 hex>","peer":"alice","index":0}
```

Valid if the torrent exists, `peer` is a non-empty string, and `index`
is an integer in `0 .. piece_count-1`. Adds `index` to that peer's have
set.

### `piece`

```json
{"bt":"piece","info_hash":"<64 hex>","peer":"alice","index":0,"data":"<hex>"}
```

Valid if `have` would be valid, `data` is non-empty lowercase hex of
even length, and `sha256_hex(bytes(data))` equals `pieces[index]`.
Stores the bytes and marks the peer as having `index`.

### `request`

```json
{"bt":"request","info_hash":"<64 hex>","peer":"bob","index":0}
```

Valid if `have` would be valid. `receive` does not mutate. A node
that stored that piece MAY broadcast a `piece` in response. That
response is node behaviour, not object state.

## Snapshot

`torrents` keyed by info hash (Unicode code-point order). Each entry:

| Field | Rule |
|---|---|
| `name` | Torrent name |
| `pieces` | Piece hashes in index order |
| `data` | Verified payloads, keys `"0"`, `"1"`, … (no leading zeros) |
| `have` | Peer → sorted unique indices; peer keys sorted |
| `complete` | Peers whose have set contains every index, sorted |

This is not a consensus object. `is_valid` rejects a bad message.
`receive` applies one that passed. The snapshot is the default empty
memento, `normalize("", [])`. `is_merkelized()` is false. Piece hashes
are content checks, not a chain head.

`conformance/vectors/bittorrent-swarm.json` pins a seed, a have, a
rejected corrupt piece, and an idempotent metainfo.

The Level 0 mesh node (`connect` / `send` / `ids` / `quit`) does not
implement this feature. Swarm attach is a client on `Mesh.on_app`
(`bt_node` / `bt-node`).
