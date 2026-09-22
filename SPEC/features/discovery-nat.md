# discovery.nat

Pedagogical NAT traversal for a Mesh client. STUN Binding (RFC 5389, IPv4
only), a one-byte UDP hole punch, and an `app.nat` introduction relay.

This module does not open sockets and it is not imported by the core node
binaries. The caller sends the datagrams and envelopes this module returns.
`ctl.hello` is unchanged. `discovery.peer` is unchanged: `advertise()` is an
address the client may place in an existing `ctl.peers` list.

Full TURN, ICE, and IPv6 are out of scope.

## UDP guard

The session starts disarmed. `arm(transport)` returns true only when
`transport` is the string `udp`, and that is the only value that leaves the
session armed. `UDP`, `tcp`, and any other value disarm it and return false.
The last call wins.

While disarmed, `observe_stun`, `punch`, `observe_punch`, `relay_request`,
and `handle` fail and do not change mapped state, the opened set, or the
seen set. `advertise` and `external_address` still report the current values.

## Addresses

`listen`, `external`, `relay`, and every peer address use the
`discovery.peer` address grammar. Comparison is exact. There is no
`is_connect_allowed` check: a mapped address is often a public `host:port`,
and refusing it would make the traversal useless. The TCP node connect
policy is unchanged.

`listen` is required. `external` and `relay` are optional (`null` means
absent). An empty string or any other invalid address is a `ProtocolError`
at construction. A configured `external` is the mapped address for the life
of the session.

## STUN

Magic cookie `0x2112A442`. Transaction id is 12 bytes. On the wire, ids and
packets are lowercase hex. Uppercase hex, an odd length, and a transaction
id that is not 12 bytes are rejected.

`binding_request(txid)` returns `{ok, packet}`. On success `packet` is 20
bytes: type `0x0001`, length `0`, magic cookie, transaction id. On failure
`ok` is false and `packet` is `""`.

`binding_success(txid, host, port)` returns `{ok, packet}`. `host` is IPv4
in dotted decimal with no leading zeros. `port` is an integer in
`1..=65535` (`true`/`false` are not integers). The packet is a Binding
success, type `0x0101`, whose single attribute is XOR-MAPPED-ADDRESS
(`0x0020`):

| Offset | Value |
|---|---|
| 0 | `0x00` |
| 1 | `0x01` (IPv4) |
| 2..4 | port XOR `0x2112`, big-endian |
| 4..8 | address octets XOR `21 12 a4 42` |

`parse_binding_response(packet, txid)` returns `{ok, host, port}`.

1. Reject unless both arguments are lowercase hex and the transaction id is
   12 bytes and the packet is at least 20 bytes.
2. Type must be `0x0101`. Magic cookie must match. Transaction id must
   match. The length field must equal `len(packet) - 20`.
3. Walk attributes from offset 20. Each is type, length, value, then
   padding to a 4-byte boundary. A truncated attribute or padding that
   would pass the length fails the message. The walk must end on the
   length boundary.
4. The first XOR-MAPPED-ADDRESS is used. Other attributes are skipped.
   Its value must be 8 bytes, reserved byte `0x00`, family `0x01`. The
   decoded port must be in `1..=65535`.
5. `host` is the four decoded octets in decimal with no leading zeros.

On failure `ok` is false, `host` is `""`, and `port` is `0`.

`observe_stun(packet, txid)` parses a success and stores `host:port` as the
mapped address. It returns false, and does not change the mapped address,
when the session is disarmed, when `external` was configured, when the
parse fails, or when `host:port` is not a `discovery.peer` address.

## Advertise

`external_address()` is the mapped address, or `""` when none is known.

`advertise()` is the mapped address when one is known, otherwise `listen`.

## Hole punch

The punch datagram is the single byte `0x00`, hex `00`.

`punch(peer)` returns `{ok, datagram, addr}`. Success requires an armed
session and a valid `peer` that is neither `listen` nor `advertise()`.
`datagram` is `00` and `addr` is `peer`. Otherwise `ok` is false,
`datagram` is `""`, and `addr` is `""`. Punching does not change `opened`.

`observe_punch(datagram, from)` returns true when the session is armed,
`datagram` is `00`, and `from` is a valid address other than `listen` or
`advertise()`. The address is appended to `opened` if absent. A repeat
observance stays true and does not move the entry. Anything else returns
false and changes nothing.

`opened()` is that list in insertion order.

## Relay

Relay messages are JSON objects carried as the `data` of an `app.nat`
envelope. Extra keys are ignored and are not copied into a reply.

`relay_request(target)` returns `{ok, message}`. Success requires an armed
session, a configured `relay`, and a valid `target` that is not `listen`,
not `advertise()`, not `relay`, and not already in `opened`. The message is:

```json
{"from":"<advertise>","nat":"request","relay":"<relay>","target":"<target>"}
```

Otherwise `ok` is false and `message` is null.

`handle(message)` returns `{ok, action, addr, reply}`. Failure is
`ok` false, `action` `""`, `addr` `""`, `reply` null. Failure leaves
`opened` and the seen set unchanged.

The message must be an object. `nat` is `request` or `response`. `from`
and `target` are valid addresses. A request also requires a valid `relay`.
`from` equal to `listen` or `advertise()` is rejected.

A message already handled (same `nat`, `from`, `target`, and, for a
request, `relay`) is rejected.

Otherwise, in order:

1. `target` is `listen` or `advertise()`. `action` is `punch` and `addr`
   is `from`. A request's `reply` is
   `{"from":"<advertise>","nat":"response","target":"<from>"}`.
   A response has `reply` null and appends `from` to `opened` if absent.
2. Else if `nat` is `request` and `relay` is `listen` or `advertise()`,
   `action` is `forward`, `addr` is `target`, and `reply` is the request
   reduced to `from`, `nat`, `relay`, and `target`. `opened` is unchanged.
3. Else reject, without recording the message.

`conformance/vectors/discovery-nat.json` pins the codec and the session.
