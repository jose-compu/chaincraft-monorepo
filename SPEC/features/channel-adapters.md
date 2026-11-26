# channel adapters

**Release:** 1.12.1

Live delivery for the schemes in `wire.channel`, other than `tcp` and `loop`.
`ctl.hello.listen` stays one `host:port` string. These adapters do not add a
field to `ctl.hello` and do not change envelope `v`.

`udp` is a localhost datagram socket. `pipe` is an in-process datagram pipe
with the same byte cap, for simulating a mesh on one computer. `mailto`,
`webrtc`, and `forum` are in-memory buses: this release has no SMTP server,
no ICE agent, and no HTTP forum. A bus is the allow-list. A message is delivered
only to an address that is listening on that bus. The pipe does not bind a
kernel socket. PeerJS signaling and the cross-scheme relay are
`channel.peer`.

## Bus

`AdapterBus(scheme, max_bytes)` and `AdapterChannel` use the same operations
as the loop channel.

| Scheme | Address | Max decoded bytes |
|---|---|---|
| `udp` | `udp://host:port` | 65507 |
| `mailto` | `mailto:local@domain` | 4096 |
| `webrtc` | `webrtc:<peer id>` | 65507 |
| `forum` | `forum:<profile>:<thread>` | 4096 |
| `pipe` | `pipe:<name>` | 65507 |

`listen` succeeds only for this scheme, only once, and only when that
canonical address is free. `dial` is true when the address is bound.
`send(addr, data)` appends `{data, from}` to that inbox. `data` is lowercase
hex of 1..=max_bytes decoded bytes. `from` is the sender's listen address, or
`""`. `recv` returns the inbox in order and clears it. `close` unbinds.

A repeated forum post is stored again. Dedup of envelope ids is the caller's
job, not the board's.

## UDP socket

`UdpLink.bind()` binds `127.0.0.1:0`. `host_port` is `127.0.0.1:<port>`.
`send(host_port, body)` writes one datagram. `body` length is `1..=65507`.
`recv` returns `(host_port, body)`. This socket is not the `ctl.hello`
`listen` field. The TCP mesh does not bind it unless a caller does.

`conformance/vectors/channel-adapters.json` pins one exchange per scheme.
The localhost socket is covered by a language test, not by a vector, because
the port is assigned at bind time.

A performance test puts four peers on one pipe bus and delivers 65536
messages of 128 decoded bytes. It prints deliveries per second. A run that
takes 30 seconds or more has failed. The rate is not a golden vector.
