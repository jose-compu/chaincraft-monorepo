# cli.node

**Release:** 1.0.0

JSON-lines command surface for a node process. The live interop runner
(`conformance/runner/run_interop.py`) speaks this protocol on stdin and
stdout.

This is the command parser and session state. Opening sockets, framing
and gossip are `wire.*` and the mesh node. A conforming implementation
MUST accept the commands below and emit the events below. The wall clock
MUST NOT be read; envelope ids are payload digests and do not depend on
time.

## Line

Each stdin line is one command. A line that is empty or only whitespace
is ignored: no event, no state change.

A line that is not canonical-JSON-parseable is
`{"event":"error","message":"invalid json"}`.
A JSON value that is not an object is the same error.

## Commands

| `cmd` | Fields | Effect |
|---|---|---|
| `connect` | `addr` | If `addr` is a valid `discovery.peer` address, append it to `peers` unless already present, then emit `connected`. Otherwise emit `invalid address`. |
| `send` | `type`, `data` | If `type` matches `^[a-z0-9._-]{1,64}$` and `data` is canonicalizable, append the payload digest to `ids` and emit `sent`. Otherwise emit `invalid send`. |
| `ids` | — | Emit the recorded send ids in insertion order. |
| `quit` | — | Set `closed` and emit `quit`. |

Any other `cmd`, or a missing `cmd`, emits
`{"event":"error","message":"unknown cmd"}`.

After `quit`, every subsequent non-empty line emits
`{"event":"error","message":"closed"}`.

`start()` emits `{"event":"ready","addr":"<listen>","impl":"<impl>"}`.
`listen` is a constructor string (the advertised bind address). `impl`
is a non-empty constructor string.

## Events

Every event is an object with an `event` string. Fields:

| event | Fields |
|---|---|
| `ready` | `addr`, `impl` |
| `connected` | `addr` |
| `sent` | `id` (64 lowercase hex) |
| `ids` | `ids` (array of hex ids) |
| `quit` | — |
| `error` | `message` |

## Snapshot

`peers` in insertion order, `ids` in insertion order, `closed`.

`conformance/vectors/cli-node.json` pins start, connect, send, ids,
unknown commands and the closed session.
