# discovery.ban

**Release:** 1.12.2

Process-local strike list that bans a peer and stops relay of that peer's gossip.
The set is not gossiped, not written to disk, and not part of the core node CLI.
The caller passes `now_ms`; the object does not read a clock.

Wire envelope `v` stays 1. Mesh integration is via `allow_peer` / `allowPeer` and
optional use of `classify_inbound` before `note`.

## Constructor

- `strike_limit`: positive integer, default 3. Non-positive values and booleans are rejected.
- `ban_ttl_ms`: positive integer, default 60000. Non-positive values and booleans are rejected.

Python raises `ValueError`. Rust returns `Err(String)`. TypeScript throws `Error`.

At most `MAX_TRACKED` (64) peers are held in insertion order. Re-noting an existing
peer does not change its position. A new peer beyond the cap evicts the oldest peer
that is not currently banned. If all 64 slots hold active bans, a new peer is ignored.

## Reasons

`note(peer, reason, now_ms)` accepts exactly:

| reason | effect |
|---|---|
| `digest_flood` | one strike |
| `malformed` | one strike |
| `invalid_address` | immediate ban; strikes set to `strike_limit` |

Any other reason, an invalid `peer` address, boolean `now_ms`, or `now_ms < 0` yields
`ignored` with no mutation.

## note outcomes

Returns one of `strike`, `banned`, or `ignored`.

When strikes reach `strike_limit`, the call returns `banned` and stores
`banned_at = now_ms`. Strikes stay at that count.

A note for a peer that is already banned returns `banned` without adding strikes or
moving `banned_at`.

`is_banned(peer, now_ms)` is true while `now_ms - banned_at <= ban_ttl_ms`. When
`now_ms - banned_at > ban_ttl_ms` the peer is cleared: not banned and strikes 0.

`strikes(peer)` is 0 when the peer is absent.

`banned(now_ms)` returns banned addresses sorted by Unicode code point after applying
expiry.

## classify_inbound

`classify_inbound(type, solicited, duplicate, address_ok)` does not mutate.

| Input | action | reason |
|---|---|---|
| `ctl.peers` and `solicited` is false | `ignore` | null |
| type starts with `ctl.` or `link.` | `deliver` | null |
| `address_ok` is false | `drop` | `invalid_address` |
| `duplicate` is true | `drop` | `digest_flood` |
| otherwise | `deliver` | null |

`ignore` matches `discovery.local`: unsolicited `ctl.peers` is not a strike and must
not be passed to `note`. `drop` means the caller may `note` that reason and must not
relay.

## Mesh gate

Default allow-all so existing nodes behave unchanged:

- Python: `Mesh(..., allow_peer=None)` allows every address.
- Rust: `set_allow_peer` optional; default allows all.
- TypeScript: `allowPeer` defaults to `() => true`.

In TCP `_handle` and the UDP datagram handler, `ctl.*` keeps the existing path,
including `ctl.hello`. For any other frame, a false `allow_peer` returns before dedup,
relay, `on_link`, and `on_app`. The socket stays up. Nothing is recorded in the dedup
set for that frame.

`conformance/vectors/discovery-ban.json` pins constructor, note, expiry, capacity,
`classify_inbound`, and sort order.