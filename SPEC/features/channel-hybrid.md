# channel.hybrid

**Release:** 1.12.0

One mesh. Each member has one channel for the life of the link. Gossip
accepted from a member is delivered to every other member whose hop can
hold the envelope bytes. `link.*` and `ctl.*` are delivered to one member.
`ctl.hello.listen` stays one `host:port` and is not stored on this mesh.

`mailto` and `webrtc` stay the in-memory adapters. This feature does not
open an SMTP session or an ICE data channel. `udp` on the live TCP mesh is
an optional localhost datagram listener.

## Members

`join(addr)` is true when `parse_address` succeeds, the scheme has a hop
cap, and that canonical address is not already a member.

| Scheme | Max envelope bytes |
|---|---|
| `tcp` | 262144 |
| `udp` | 65507 |
| `webrtc` | 65507 |
| `pipe` | 65507 |
| `mailto` | 4096 |
| `forum` | 4096 |
| `loop` | 64 |

## Delivery

`gossip(src, type, data)` builds an envelope with `ts` fixed at 0. `src`
must be a member. `type` must be a gossip type. The first time that payload
id is accepted, every other member receives `{id, type, from}` when
`len(envelope bytes) <=` that member's cap. A later accept of the same id
returns the id and delivers nothing. A member whose cap is too small is
skipped. The other members still receive it.

`direct(src, dst, type, data)` is the same build, for a `ctl.*` or `link.*`
type, and the item is appended only to `dst` when that hop can hold it.

`take(addr)` returns that inbox in arrival order and clears it.

`from` is the canonical source address.

## UDP listener

`hello_caps(udp)` is `digest-sync`, `gossip`, and `udp` when the datagram
listener is open. Without it, the caps are `digest-sync` and `gossip`.
Both lists are sorted.

The TCP mesh may bind `127.0.0.1:0` and `connect` to `udp://host:port`.
One datagram is one envelope. A gossip envelope that arrives on UDP is
relayed to the TCP peers and to the other UDP peers, and is not sent back
to the sender. A browser build does not bind this socket and does not
advertise `udp`.

`conformance/vectors/channel-hybrid.json` pins the caps and one relay
transcript. The localhost datagram exchange is a language test.
