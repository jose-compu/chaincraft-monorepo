# app.stream

**Release:** 1.8.0

Leaderless append-only event log. Nodes that have accepted the same
messages hold the same partitions, records, replica set, retention, and
consumer-group cursors. There is no leader and no rebalance.

This is not `app.pubsub`. That object is a chat room. A stream is the
event log: batch append, partitions, replica brokers, a retained tail,
and a local range read. The two objects do not share messages.

The object implements the Level 1 contract (`SPEC/semantics-v1.md` §2)
and is applied through the ordinary pipeline. A dapp gossips each
operation as an envelope whose `type` is `app.stream` and whose `data` is
one message below. `app.stream` is gossip under `wire.paths`.

`read` is not a message. It is a local query. It is not gossiped and it
does not change state.

## What this object covers

These are the rudimentary forms of the usual streaming properties. They
are not a broker cluster.

| Property | In this object |
|---|---|
| Throughput | `append` carries up to `MAX_BATCH` records in one message. `retain` bounds the stored tail so ingest can continue. |
| Scale | A stream has partitions `0..MAX_PARTITIONS-1`. Opening a new partition does not reject traffic on another. `join` adds a replica broker without removing records. |
| Durability | Records live in the object. `fail` marks a broker down and deletes nothing. Every node that has applied the same messages still holds the log. |
| Fault tolerance | If the replica set is empty, the mesh holds the log and `read` works. If it is not empty, `read` and the data-plane ops work while at least one broker is `up`. |
| Decoupling | `produce` and `append` do not name a consumer group. `commit` does not require the producer to have listed that group. |
| Replay and retention | `read` from a null cursor returns the retained tail. A later group can commit that tail. Trimmed sequences stay gone. |
| Pipelines | A stage is ordinary use: `read` one stream, `produce` another. The object does not couple the two streams. |

## Limits

| Name | Value |
|---|---|
| `MAX_STREAMS` | 32 |
| `MAX_PARTITIONS` | 16 partitions in one stream |
| `MAX_PRODUCERS` | 32 producers in one partition |
| `MAX_EVENTS` | 64 events stored in one partition |
| `MAX_GROUPS` | 32 consumer groups in one partition |
| `MAX_BROKERS` | 8 replica brokers in one stream |
| `MAX_BATCH` | 64 records in one `append` |
| `MAX_PAYLOAD` | 4096 Unicode scalar values |
| `MAX_READ` | 256 events returned by one `read` |
| name | 1 to 64 characters, each in `A–Z`, `a–z`, `0–9`, `.`, `_`, `-` |

A name is a `stream`, a `producer`, a `group`, or a `broker`. The empty
string, a space, and any character outside that set are rejected. Length
is the number of characters, not bytes.

A partition id is an integer in `0..MAX_PARTITIONS-1` and is not a
boolean. A missing `partition` means `0`.

## Messages

Every message is an object. `app` is exactly `stream`. `op` is exactly
`open`, `produce`, `append`, `commit`, `join`, `fail`, or `retain`. Extra
keys are ignored.

```json
{"app":"stream","op":"open","stream":"orders","producer":"alice","partition":0}
{"app":"stream","op":"produce","stream":"orders","producer":"alice","seq":0,"payload":"created","partition":0}
{"app":"stream","op":"append","stream":"orders","partition":0,"records":[{"producer":"alice","seq":1,"payload":"next"}]}
{"app":"stream","op":"commit","stream":"orders","group":"workers","producer":"alice","seq":0,"partition":0}
{"app":"stream","op":"join","stream":"orders","broker":"n1"}
{"app":"stream","op":"fail","stream":"orders","broker":"n1"}
{"app":"stream","op":"retain","stream":"orders","keep":32}
```

`payload` is a string of 1 to `MAX_PAYLOAD` Unicode scalar values. `seq`
is an integer in `0..=2^53-1` and is not a boolean. `keep` is an integer
in `1..=MAX_EVENTS` and is not a boolean. `records` is an array of 1 to
`MAX_BATCH` objects. Each object has `producer`, `seq`, and `payload`.
Extra keys on a record are ignored.

## Availability

Each stream has a replica set. A broker is `up` or `down`.

- The set is empty: the mesh holds the log. Data-plane ops and `read` are available.
- The set is non-empty and at least one broker is `up`: available.
- The set is non-empty and every broker is `down`: unavailable.

`join`, `fail`, and `retain` are control-plane. They do not require
availability. `open`, `produce`, `append`, `commit`, and `read` do.
Unavailable `read` returns `[]`. An unavailable data-plane message is
rejected. Records are not deleted when the stream becomes unavailable.

## `is_valid`

False unless all of the following hold. `is_valid` has no side effects.
A rejected message leaves state unchanged.

`open`

- `stream` and `producer` are names, and the partition id is in range
- the stream is available, or it does not exist yet
- the stream already exists, or the object has fewer than `MAX_STREAMS`
- the partition already exists, or the stream has fewer than `MAX_PARTITIONS`
- the producer is already open on that partition, or the partition has fewer than `MAX_PRODUCERS`

A second open by the same producer on the same partition is accepted and
changes nothing. An open on a new partition does not change any other
partition.

`produce`

One record on one partition. The stream exists and is available. The
producer is open there. The record is acceptable under **Records** below.

`append`

The stream exists and is available. `records` is in range. The records
are acceptable together under **Records**, applied in array order, all or
nothing. One bad record rejects the message and stores none of them.

`commit`

- `stream`, `group`, and `producer` are names, the partition id and `seq` are in range
- the stream exists and is available
- the producer is open on that partition
- the record `(producer, seq)` is stored there
- the retained prefix for that producer is closed at `seq` (below)
- the group already exists on that partition, or the partition has fewer than `MAX_GROUPS`

The producer message does not name the group. A group the producer has
never mentioned is a valid new group.

A commit at or below that group's current cursor for that producer is
accepted and changes nothing. A higher `seq` advances the cursor. One
group does not constrain another. Trim does not remove cursors.

`join`

- `stream` and `broker` are names
- the stream already exists, or the object has fewer than `MAX_STREAMS`
- the broker is already in the set, or the set has fewer than `MAX_BROKERS`

A join of a new broker adds it as `up`. A join of a `down` broker marks
it `up`. A join of a broker that is already `up` changes nothing. Join
does not drop records and does not reject later produce on an available
stream.

`fail`

- `stream` and `broker` are names
- the broker is in the set

The broker is marked `down`. Records stay. Failing a broker that is
already `down` changes nothing.

`retain`

- `stream` is a name and the stream exists
- `keep` is in `1..=MAX_EVENTS`

The stream's retention becomes `keep`. Each partition then drops oldest
records until it stores at most `keep`. Raising `keep` does not restore
trimmed records. The default retention, before any `retain`, is
`MAX_EVENTS`.

Any other `op`, a missing field, or a message whose `app` is not
`stream` is rejected.

## Records

Used by `produce` and, in order, by `append`.

Let `mark` be that producer's trim watermark on the partition, or `-1`
if that producer has not had a contiguous prefix trimmed.

- `seq <= mark` is rejected. A trimmed sequence is not produced again.
- The same `(producer, seq, payload)` already stored is accepted and is not a new record, including at the caps.
- A different payload for the same `(producer, seq)` is rejected.
- Otherwise the record is new. It is rejected if the partition already stores `MAX_EVENTS` records. It is stored, then the partition drops oldest records until it stores at most the stream retention.

A gap is accepted. `seq` 2 may be stored while `seq` 1 is absent.

Dropping the oldest record removes the stored pair with the lowest `seq`,
then the lowest `producer` in code-point order. If that `seq` equals
`mark + 1` for its producer, `mark` becomes that `seq`. A drop that skips
a gap does not move `mark`.

The retained prefix at target `seq` is closed when the record is stored
and the number of stored records for that producer with `seq` in
`mark+1..=target` equals `target - mark`. The check counts stored
records. It does not walk the integers `0..=target`.

## `add_message`

`is_valid` is the check above. `receive` applies a message that passed it.
`add_message` is the default: it calls `receive` and returns nothing.

`open` adds the producer, creating the stream and the partition when
needed.

`produce` and `append` store records as in **Records**. `append` applies
`records` from first to last.

`commit` creates the group when needed and sets that producer's cursor
when the new value is higher.

`join` creates the stream when needed and records the broker.

`fail` marks the broker `down`.

`retain` sets retention and trims.

## `read`

```
read(stream, partition, after, limit) -> events
```

Returns a list. It does not mutate. The result is `[]` unless every item
below holds.

- `stream` is a stream that exists here, and that stream is available
- `partition` is an in-range id and that partition exists
- `limit` is an integer in `1..=MAX_READ` and is not a boolean
- `after` is null, or an object whose `producer` is a name and whose `seq` is in `0..=2^53-1` and is not a boolean

Otherwise the records of that partition, sorted by `seq` ascending then
by `producer` in Unicode code-point order.

`after` null starts at the first retained record. Otherwise the list is
the records strictly after `(seq, producer)` in that sort order. The
cursor need not name a stored record. The list is truncated to `limit`
events. Extra keys on `after` are ignored.

A new consumer replays by reading with `after` null. It sees only the
retained tail.

## Snapshot

`streams` is every stream that exists, sorted by name in Unicode
code-point order.

Each stream has `retention`, `replicas`, and `partitions`. `retention` is
the integer keep count. `replicas` is the brokers sorted by name, each
`{broker, status}` with `status` exactly `up` or `down`. `partitions` is
the partitions that exist, sorted by id.

Each partition has `partition`, `producers`, `events`, `groups`, and
`trimmed`. Producers are sorted by name. Events are sorted by `seq`
ascending, then by `producer`. Groups are sorted by name. Each group has
`cursors`, sorted by producer, each `{producer, seq}` the highest
committed seq. `trimmed` is the producers whose watermark is at least 0,
sorted by producer, each `{producer, seq}` that watermark. Arrival order
is not part of the log.

```json
{"streams":[{"name":"orders","retention":64,"replicas":[{"broker":"n1","status":"up"}],"partitions":[{"partition":0,"producers":["alice"],"events":[{"producer":"alice","seq":0,"payload":"created"}],"groups":[{"name":"workers","cursors":[{"producer":"alice","seq":0}]}],"trimmed":[]}]}]}
```

`add_message` returns nothing. The snapshot is the default empty memento,
`normalize("", [])`. `is_merkelized()` is false. The log above is the
object's state. It is not a chain head.

`conformance/vectors/app-stream.json` pins open, produce, append, commit,
partitions, replica failure, retention, replay, a two-stream pipeline,
caps, and rejection. Performance tests ingest 65536 records through
`append` with retention 32, on two partitions, and print records per
second. They are not part of the golden file. A run that takes 30 seconds
or more has failed. The Rust performance test, built without debug
assertions, ingests 1048576 records the same way. A release run is the
high-throughput check; its rate is printed and is not a golden vector.
