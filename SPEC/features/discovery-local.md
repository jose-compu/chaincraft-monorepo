# discovery.local

**Release:** 1.10.0

Policy for filling the address book from a neighbor's current peer list.

The wire is `ctl.peers.request` / `ctl.peers` (wire-v1 §5.2). This feature
does not introduce new message types. It decides when those messages are
sent, answered and ingested.

`discovery.peer` is required: the address book is the store.

## Enabled flag

Default: enabled.

| Operation | Enabled | Disabled |
|---|---|---|
| `request(peer)` | mark `peer` solicited; return true if `peer` is a valid address | do not mark; return false |
| `reply()` | return `advertise()` | return no list |
| `accept(from, addresses, now_ms)` | ingest only if `from` is solicited, then clear that mark | return 0, leave the book unchanged |

A disabled node still accepts user-requested `insert` calls. It does not
share or learn peer lists over the control channel.

## Request

`request(peer)` is what a node does after an explicit local-discovery
connect (legacy `connect_to_peer_locally`). It does not insert `peer`.

## Reply

`reply()` is the body of a `ctl.peers` response. Disabled nodes MUST NOT
answer a `ctl.peers.request` with their list. They MAY ignore the request
or disconnect; they MUST NOT leak addresses.

## Accept

`accept(from, addresses, now_ms)` handles an incoming `ctl.peers`.

1. If disabled, return 0.
2. If `from` is not solicited, return 0.
3. Clear the solicitation mark.
4. `ingest(addresses, now_ms, solicited=true)` on the book.

The unsolicited-list rule of `discovery.peer` still applies: a `ctl.peers`
that arrives without a prior `request` is ignored even when enabled.

`conformance/vectors/discovery-local.json` pins the enabled and disabled
paths against the same address book.
