# wire.channel

**Release:** 1.12.0

Address URIs and an in-process loop channel. UDP, email, WebRTC, forum,
and the in-process pipe are `SPEC/features/channel-adapters.md`. TCP
remains the mesh. `ctl.hello.listen` stays one `host:port`.

Envelope bytes, payload digests and Level 1 objects MUST NOT depend on
the channel. `ctl.hello.listen` remains a single `host:port` string
(wire-v1 §5.1). A list of listen URIs is adapter state, not a Level 0
change.

Bare `host:port` is accepted as `tcp://host:port` so `discovery.peer`
addresses remain valid. The stored / advertised form of the address book
is unchanged.

## Schemes

| Scheme | Form | Cap |
|---|---|---|
| `tcp` | `tcp://host:port` | `tcp` |
| `udp` | `udp://host:port` | `udp` |
| `mailto` | `mailto:local@domain` | `mailto` |
| `webrtc` | `webrtc:<peer id>` | `webrtc` |
| `forum` | `forum:<profile>:<thread>` | `forum` |
| `loop` | `loop:<name>` | `loop` |
| `pipe` | `pipe:<name>` | `pipe` |

Schemes are lowercase. `TCP://…` is rejected.

`host:port` in `tcp` / `udp` (and a bare address) uses the
`discovery.peer` address grammar. The rest after `://` MUST be exactly
that grammar: no userinfo, path, query or fragment (`@`, `/`, `?`, `#`
are rejected).

`local` is 1–64 characters of `A-Za-z0-9._+-`. `domain` is a
`discovery.peer` host (IPv4 or hostname). Exactly one `@`.

`profile`, `loop` `name`, and `pipe` `name` are 1–32 characters of
`a-z0-9-`, not starting or ending with a hyphen. `thread` is 1–64 characters of
`A-Za-z0-9._-`. `forum` rest contains exactly one `:`.

A `webrtc` peer id is 1–64 characters of `A-Za-z0-9_-`. A 64-character
lowercase hex id remains valid. The same grammar is `channel.peer`.

## Parse

`parse_address(raw)` returns `{ok, scheme, canonical, cap}`.

1. Reject if `raw` is not a non-empty string.
2. If `raw` contains `://`, split on the first `://`. The scheme MUST be
   `tcp` or `udp`. The rest MUST be a valid `discovery.peer` address and
   MUST NOT contain `@`, `/`, `?` or `#`. `canonical` is
   `scheme://` + rest.
3. Else if `raw` starts with `mailto:`, `webrtc:`, `forum:`, `loop:`, or
   `pipe:`, parse the rest as that scheme. `canonical` is `scheme:` + the
   accepted rest (no case folding).
4. Else if `raw` is a valid `discovery.peer` address, succeed as
   `scheme=tcp`, `canonical=tcp://` + raw, `cap=tcp`.
5. Else reject.

On rejection every field other than `ok` is the empty string.

No normalization of case. Comparison is exact on `canonical`.

## Connect policy

`is_connect_allowed(raw)` is false when parse fails.

If `scheme` is `tcp` or `udp`, apply `discovery.peer`
`is_connect_allowed` to the `host:port` rest. Other schemes are allowed
at this layer; adapter allow-lists are a later feature.

## Loop channel

A `LoopBus` is a shared in-memory multiplex. Each `LoopChannel` bound to
that bus has one optional listen address and a FIFO inbox.

Prototype limits:

| Cap | Value |
|---|---|
| payload | 64 bytes |
| name | 32 characters (scheme rule) |

Payloads are lowercase hex of the raw envelope bytes. No TCP length
prefix. Empty payloads are rejected. Uppercase hex is rejected. Decoded
length MUST be `1..=64`.

`listen(addr)` succeeds only when `addr` parses as `loop`, the channel
is not already listening, and no other channel on the bus holds that
canonical address. The listen address is the canonical form.

`dial(addr)` is true iff `addr` parses as `loop` and that address is
bound on the bus. It does not send bytes. Send does not require a prior
dial.

`send(addr, data)` delivers `{from, data}` to the bound inbox when
`addr` is a bound `loop` address and `data` is a valid payload. `from`
is the sender's listen address, or `""` if the sender has not listened.

`recv()` returns the inbox in insertion order and clears it.

`close()` unbinds, clears the inbox, and leaves the channel not
listening. A later `send` to that name fails until someone listens again.

`conformance/vectors/wire-channel.json` pins parse, connect policy, and
a two-peer loop sequence.
