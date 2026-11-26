# app.pubsub

**Release:** 1.12.0

Topic publish-subscribe. A chat room is one topic. There is no leader, no
round, and no fork choice. Nodes that have accepted the same messages hold
the same membership and the same log.

An append-only event log, with producer sequences, a range read, and
consumer-group cursors, is `app.stream`. This object does not provide that.

The object implements the Level 1 contract (`SPEC/semantics-v1.md` §2) and
is applied through the ordinary pipeline. A chat dapp gossips each
operation as an envelope whose `type` is `app.pubsub` and whose `data` is
one message below.

## Limits

| Name | Value |
|---|---|
| `MAX_ROOMS` | 32 |
| `MAX_MEMBERS` | 32 members in one room |
| `MAX_POSTS` | 64 posts in one room |
| `MAX_TEXT` | 1024 Unicode scalar values |
| name | 1 to 64 characters, each in `A–Z`, `a–z`, `0–9`, `.`, `_`, `-` |

A name is a `room` or an `author`. The empty string, a space, and any
character outside that set are rejected. Length is the number of
characters, not bytes.

## Messages

Every message is an object. `app` is exactly `pubsub`. `op` is exactly
`subscribe`, `unsubscribe`, or `publish`. Extra keys are ignored.

```json
{"app":"pubsub","op":"subscribe","room":"general","author":"alice"}
{"app":"pubsub","op":"unsubscribe","room":"general","author":"alice"}
{"app":"pubsub","op":"publish","room":"general","author":"alice","text":"hello","seq":0}
```

`text` is a string of 1 to `MAX_TEXT` Unicode scalar values. `seq` is an
integer in `0..=2^53-1` and is not a boolean. A publish without `text` or
`seq` is rejected.

## `is_valid`

False unless all of the following hold. `is_valid` has no side effects.

`subscribe`

- `room` and `author` are names
- the author is already a member, or the room has fewer than `MAX_MEMBERS`
- the room already exists, or the object has fewer than `MAX_ROOMS`

A second subscribe by the same author is accepted and changes nothing.

`unsubscribe`

- `room` and `author` are names
- the author is currently a member of that room

`publish`

- `room` and `author` are names, `text` and `seq` are in range
- the author is currently a member
- no post in that room already has this `author` and `seq`
- the room has fewer than `MAX_POSTS`

Any other `op`, a missing field, or a message whose `app` is not
`pubsub` is rejected.

## `add_message`

`is_valid` is the check above. `receive` applies a message that passed it.
`add_message` is the default: it calls `receive` and returns nothing.

`subscribe` adds the author to the room, creating the room when needed.

`unsubscribe` removes the author. The room is dropped only when it then
has no members and no posts. Posts already accepted stay.

`publish` stores `(author, seq, text)`.

## Snapshot

`rooms` is every room that has a member or a post, sorted by name in
Unicode code-point order.

Each room has `members` (sorted the same way) and `posts`. Posts are
sorted by `seq` ascending, then by `author` in code-point order. Arrival
order is not part of the log. Two posts with the same `seq` from
different authors both remain; the lower author is listed first.

```json
{"rooms":[{"name":"general","members":["alice","bob"],"posts":[{"author":"alice","seq":0,"text":"hello"}]}]}
```

`add_message` returns nothing. The snapshot is the default empty memento,
`normalize("", [])`. `is_merkelized()` is false. The room log above is the
object's state. It is not a chain head.

`conformance/vectors/app-pubsub.json` pins a chat room, two rooms, log
order, repeats, rejection, and the caps.
