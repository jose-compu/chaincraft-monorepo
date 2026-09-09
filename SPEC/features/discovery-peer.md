# discovery.peer

Address book for `host:port` peers. Used by `ctl.peers.request` / `ctl.peers`
(wire-v1 §5.2) and by `discovery.local`.

This is not a transport. Connecting, dialing and NAT traversal are out of scope.
The book decides which addresses are remembered, advertised and expired.

## Defaults

| Name | Value |
|---|---|
| capacity | 50 |
| timeout | 120000 ms |

Capacity and timeout MUST be positive integers. Construction with a non-positive
value is rejected.

All times are millisecond Unix timestamps, injected by the caller. The wall
clock MUST NOT be read inside the book.

## Address format

An address is `host:port`, split on the last `:`.

`port` is a decimal integer in `1..=65535` with no leading zeros.

`host` is either:

1. **IPv4.** Four decimal octets `0..=255`, no leading zeros (`0` is allowed;
   `00` and `01` are not). A host with exactly four all-digit labels is an IPv4
   candidate: it is valid IPv4 or it is rejected. It is never reinterpreted as
   a hostname. `256.0.0.1` is therefore invalid.
2. **Hostname.** DNS-style labels of `A-Za-z0-9` and hyphen, each 1–63
   characters, not starting or ending with a hyphen. Total host length 1–253.
   No trailing or leading `.`. Underscores are rejected.

IPv6 is rejected. Brackets, paths, spaces and empty labels are rejected.

## Node connect policy

`is_valid_address` is the book format. A node CLI `connect` is stricter:
it is a prototype dial, not an open proxy.

`is_connect_allowed(addr)` is true only when `addr` is a valid address
and the host is loopback (`127.0.0.0/8` or `localhost`), RFC1918
(`10/8`, `172.16/12`, `192.168/16`), or a `.local` hostname.

After DNS resolution the node MUST dial only the first IPv4 result, and
MUST refuse it unless that IP is loopback or RFC1918. Link-local
(`169.254/16`), unspecified (`0.0.0.0`) and public addresses are
refused. IPv6 is refused. Connect MUST time out within 5 seconds.

The stored form is the input string after it has passed validation. No
normalization of case. Comparison is exact.

## Self

The book MAY be constructed with a `listen` address. That address is never
stored. Inserting it is a no-op.

## Insert

`insert(address, now_ms)`:

1. Reject (return false) if the address is invalid or equals `listen`.
2. If already present, update `last_seen` to `now_ms` and return false. Do
   **not** move it in insertion order. Re-seeing does not refresh eviction
   rank — the same rule as `wire.dedup` §7.2.
3. If at capacity, evict the oldest insertion first, then append.
4. Store `last_seen = now_ms`. Return true.

Direct inserts (a seed, a user-requested connect) may evict. That is how a
full book accepts a new neighbor.

## Ingest

`ingest(addresses, now_ms, solicited)` applies a `ctl.peers` payload.

- If `solicited` is false, do nothing and return 0. A receiver MUST NOT
  accept peer lists it did not request (wire-v1 §5.2).
- If `solicited` is true, call `insert` for each entry **without eviction**:
  skip any address that would require dropping an existing one. Invalid
  entries and `listen` are skipped. Return the number of newly stored
  addresses.

Gossip-learned peers fill remaining slots. They must not rotate the book.

## Advertise

`advertise()` returns every stored address sorted ascending by Unicode code
point. Canonical JSON preserves array order, so a sorted advertisement is a
stable `ctl.peers` payload.

## Expire

`sweep(now_ms)` removes every entry with `now_ms - last_seen > timeout`.
An entry whose `last_seen` is in the future is kept. Return the number
removed.

## Solicitation

`mark_solicited(peer)` records that a `ctl.peers.request` was sent to `peer`.
`is_solicited(peer)` reports it. `clear_solicited(peer)` forgets it.

The book does not send envelopes. The node marks before transmit and passes
`solicited=true` only for a matching response.

`conformance/vectors/discovery-peer.json` pins parsing, insert, ingest,
eviction, expiry and advertisement order.
