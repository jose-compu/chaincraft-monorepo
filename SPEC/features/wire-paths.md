# wire.paths

**Release:** 1.9.0

Two delivery paths, for every protocol. The path is the envelope `type`
prefix. Envelope `v` stays 1 and no field is added.

| Prefix | Path | Relay | Seen set | Who handles it |
|---|---|---|---|---|
| `ctl.` | control | no | no | the mesh (§5 of wire-v1) |
| `link.` | control | no | no | the application, with the peer address |
| anything else | gossip | yes | yes | the application, no peer required |

`ctl` and `link` without the dot are gossip. A repeated control payload is
delivered again. A repeated gossip payload is not.

`broadcast(type, data)` is gossip and MUST reject a control type.
`send(addr, type, data)` is control and MUST reject a gossip type. `send`
writes to that one peer. A missing peer is rejected. The receiver MUST NOT
relay it and MUST NOT store it in the application message set.

`on_link(addr, type, data)` is the only context a control message carries.
Protocols MUST NOT invent new `ctl.*` types. A protocol control message uses
`link.<name>`.

Consensus objects add a snapshot and may use `ctl.digest` and
`ctl.messages` to sync with one peer. Those types stay mesh control and are
not relayed. A non-consensus object does not.
