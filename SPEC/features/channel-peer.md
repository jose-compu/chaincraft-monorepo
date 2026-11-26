# channel.peer

**Release:** 1.11.0

PeerJS peer ids, the broker a browser uses to learn an id, and an in-memory
relay that delivers one envelope to every other joined address.

This feature does not open an ICE data channel and does not speak SMTP.
`channel.webrtc` remains the in-memory bus. A browser entry may import this
module. It MUST NOT import the TCP mesh.

## Peer id

A peer id is 1–64 characters of `A-Za-z0-9_-`. That is the `webrtc` rest in
`wire.channel`. `parse_peer_id_body(text)` trims leading and trailing
whitespace and returns the id, or nothing when the trimmed text is not a
peer id.

## Broker

`DEFAULT_PEER_ORIGIN` is `https://dechess-org-peerjs.vercel.app`.

`peer_options(origin)` returns `{host, port, path, secure, key}`:

| Field | Default |
|---|---|
| `host` | hostname of `origin` |
| `port` | the port in `origin`, else 443 for `https` and 80 for `http` |
| `path` | `/` |
| `secure` | true when the scheme is `https` |
| `key` | `peerjs` |

`origin` MUST be `http` or `https` and MUST have a hostname. Any other
origin is an error. The path and query of `origin` are ignored. `path` in
the result is always `/`.

`fetch_peer_id(origin)` performs `GET {origin}/peerjs/id`, reads the body
as text, and returns `parse_peer_id_body`. A failed request or a body that
is not a peer id is an error. The Rust crate exposes `parse_peer_id_body`
and `peer_options` and does not perform the HTTP GET.

## Relay

`EnvelopeRelay` is one process. `join(addr)` is true when `parse_address`
succeeds, the scheme is `udp`, `mailto`, `webrtc`, `forum`, or `pipe`, and
that canonical address is not already a member. `tcp` and `loop` are
refused. A second `join` of the same canonical address is false.

`publish(src, type, data)` builds an envelope with `ts` fixed at 0. It
returns the payload id when `src` is a member and `type` and `data` are
valid. The first time that id is published, every other member, in join
order, receives `{id, type, from}`. `from` is the canonical `src`. A later
`publish` of the same id returns the id and delivers nothing. An unknown
source, a refused address, or an invalid envelope returns nothing and
delivers nothing.

`take(addr)` returns that member's inbox in arrival order and clears it.
An address that is not a member returns an empty list.

`conformance/vectors/channel-peer.json` pins the id grammar, the default
broker options, and one relay transcript. A live `GET /peerjs/id` against
`DEFAULT_PEER_ORIGIN` is a language test, not a vector.
