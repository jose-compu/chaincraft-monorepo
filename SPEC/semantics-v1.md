# Chaincraft Object Semantics — v1 (Level 1)

**Status:** Draft
**Scope:** Level 1. Behaviour that MUST match across implementations so that the same
protocol, ported between languages, produces the same state. Unlike Level 0, a mismatch
here does not prevent two nodes from talking — it makes them silently disagree about the
result, which is worse.

Level 1 is verified by **replay vectors, not by wire tests**: each implementation feeds a
fixed message sequence through its pipeline and asserts the resulting digests.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be interpreted as in
RFC 2119.

---

## 1. Why this layer already almost agrees

The Python and Rust implementations independently converged on the same object model:
validate-all-then-apply, with a state snapshot threaded between objects. Level 1 exists
to pin that convergence down before it drifts, not to invent something new.

---

## 2. The application object contract

An application object exposes, in whatever form is idiomatic for the language:

| Operation | Contract |
|---|---|
| `is_valid(message) -> bool` | Deterministic and **side-effect free**. Defaults to true. |
| `receive(message)` | Local apply. Defaults to doing nothing. This is the method a prototype implements. |
| `add_message(message, frontier_state?) -> StateMemento?` | Defaults to calling `receive` and returning nothing. |
| `emit_state_memento() -> StateMemento` | Current snapshot. Used when `add_message` returns nothing. |
| `get_state_digests() -> [string]` | Frontier digests for multi-head structures (DAGs, forks). Defaults to `[]`. |
| `is_merkelized() -> bool` | Whether canonical digests are meaningful for this object. Defaults to false. |

A prototype implements `receive` and nothing else. `is_valid` stays true, so the
message is applied locally. `add_message` ignores `frontier_state` and returns
nothing. The snapshot is `normalize("", [])`: empty digest, empty frontier,
revision 0, empty metadata. An empty digest never reports a reorg (§4.2).

The pipeline is local. Peers are not required to hold the same messages. A
disconnect may drop one. An object that is not a consensus protocol tolerates
that: its state is the messages it has applied, and a later message may fill a
gap. Shared state, when it is required, is the job of a consensus object such
as `pbft`. That object overrides `add_message` and the snapshot. A chat room
does not.

Naming differs per language (`SharedObject` in Python, `ApplicationObject` in Rust).
Rust prototypes implement `Protocol`, which supplies `ApplicationObject`.
Python and TypeScript override `receive` on the shared object. The contract
does not change.

---

## 3. The apply pipeline

Given a registry of objects in **registration order** and one incoming message:

1. Call `is_valid` on **every** object.
2. If any returns false, reject the message. No object mutates. This is all-or-nothing.
3. If all pass, call `add_message` on each object in registration order.
4. Thread the memento: the value returned by object *n* is passed as `frontier_state`
   to object *n+1*. When an object returns nothing, its `emit_state_memento()` is used
   instead.
5. Persist and broadcast **only** if the whole pipeline succeeded.

Step 5 matters: committing state before the pipeline completes lets an invalid
transition reach storage, and the two implementations already agree on this ordering.

---

## 4. StateMemento

```
canonical_digest : string
frontier_digests : [string]     sorted, deduplicated, no empty entries
revision         : integer
metadata         : map<string, any>
```

### 4.1 Normalization

`normalize(canonical_digest, frontier_digests)` MUST:

1. Start from `frontier_digests` or an empty list.
2. Append `canonical_digest` if it is non-empty and not already present.
3. Drop empty strings.
4. Sort ascending by Unicode code point.
5. Deduplicate.
6. Set `revision` to `0` and `metadata` to empty.

Both existing implementations already do exactly this. The vector file
`conformance/vectors/memento.json` pins it.

### 4.2 Reorg detection

`indicates_reorg_against(previous)` returns true when **all** hold:

- `previous` exists
- both canonical digests are non-empty
- the canonical digests differ
- the previous canonical digest is **not** in the new frontier list

Meaning: the head moved to a branch that does not build on the old head.

---

## 5. Merkelized object digest

For objects reporting `is_merkelized() == true`:

```
digest = lowercase_hex( SHA-256( canonical_json(state_payload) ) )
```

Canonical JSON is defined in `wire-v1.md` §1 — the same function used for payload
digests. Using two different canonicalizations for wire hashing and state hashing is
the mistake this rule exists to prevent.

Parent linkage inside a payload uses:

- `previous_digest` — single parent, chain-shaped history
- `parents` — array of parent digests, DAG-shaped history

### 5.1 Frontier digest for multi-head objects

```
frontier_digest = sha256( canonical_json({"frontier_heads": [...sorted...], "v": 1}) )
```

The `v` field is the frontier format version and is currently `1`.

---

## 6. Replacement and tie-breaking

Where an object keeps only the latest of several competing entries:

- Higher sequence or timestamp wins.
- **On an exact tie, the lexicographically lowest digest wins.**

The tie rule is not cosmetic. Without it, two nodes holding the same two tied entries
choose differently and never reconverge.

### 6.1 Normative comparator

`rank` is the integer being compared — a sequence number or a timestamp, whichever the
object orders by. `digest` is the entry's canonical digest.

```
wins_replacement(candidate_rank, candidate_digest, incumbent_rank, incumbent_digest):
    if candidate_rank > incumbent_rank:  return true
    if candidate_rank < incumbent_rank:  return false
    return candidate_digest < incumbent_digest
```

Digest comparison is bytewise over the lowercase hex string, which for hex is equivalent
to comparing the underlying numbers.

An identical entry does not replace itself: equal rank and equal digest returns false.
Returning true there would make repeated delivery of the same message mutate state, and
gossip delivers the same message repeatedly by design.

---

## 7. Conformance

Level 1 is verified by replay vectors rather than live networking. Each implementation
runs `conformance/vectors/memento.json` and `conformance/vectors/pipeline.json` through
its own object registry and asserts the resulting digests match.

Level 1 conformance is **required**, not a later milestone. An implementation passing
Level 0 but failing Level 1 is the worst outcome available: it joins the mesh, relays
correctly, reports no errors, and computes different state. Level 0 failures are loud;
Level 1 failures are silent, which is why they are gated with equal severity.

Each feature at this level carries an entry in `SPEC/features.yaml` and is enforced by
`tools/parity_check.py` on every pull request.

---

## 8. Conformance objects

A replay vector is only portable if every implementation feeds it through *the same*
objects. This section defines two fixture objects precisely enough to reimplement. They
exist solely for conformance and are not part of the shipped API.

Both take the envelope's `data` value as their message.

### 8.1 `counter` — merkelized, chain-shaped

State: `seq` (integer, initially 0), `total` (integer, initially 0), `head` (string,
initially empty).

**`is_valid(message)`** returns true when all hold. Extra keys are ignored, which is what
lets a single message be valid here and invalid in `mirror`.

- `message` is an object
- `message.delta` is an integer in `-100 .. 100`
- `message.seq` is an integer equal to `seq + 1`

**`add_message(message, frontier_state)`**

1. `total = total + message.delta`
2. `seq = message.seq`
3. Build the state payload, using the `head` value from *before* this step as the parent:

   ```json
   {"previous_digest":"<prior head>","seq":<seq>,"total":<total>,"v":1}
   ```

4. `head = sha256_hex(canonical_json(payload))`
5. Return `normalize(head, frontier_state.frontier_digests)`, or `normalize(head, [])`
   when `frontier_state` is absent.

**`emit_state_memento()`** returns `normalize(head, [])`.
**`get_state_digests()`** returns `[head]`, or `[]` when `head` is empty.
**`is_merkelized()`** returns true.

### 8.2 `mirror` — not merkelized, records what it was threaded

Exists to prove the pipeline threads mementos in registration order. It returns nothing
from `add_message`, exercising the `emit_state_memento()` branch of §3 step 4.

State: `count` (integer, initially 0), `last_frontier` (list of strings, initially empty).

**`is_valid(message)`** returns false when `message` is an object whose `reject_mirror`
key is exactly `true`. Otherwise true.

**`add_message(message, frontier_state)`**

1. `count = count + 1`
2. `last_frontier = frontier_state.frontier_digests`, or `[]` when absent
3. Return nothing

**`emit_state_memento()`** returns `normalize("", last_frontier)`.
**`get_state_digests()`** returns `[]`.
**`is_merkelized()`** returns false.

### 8.3 Registry

Registration order is **`counter`, then `mirror`**. `mirror` therefore receives the
memento `counter` returned, and `last_frontier` records it.

### 8.4 Replay

For each message in the vector's sequence, apply it through the registry and record:

```json
{
  "accepted": true,
  "rejected_by": null,
  "counter": {"seq": 1, "total": 5, "head": "<64 hex>"},
  "mirror": {"count": 1, "last_frontier": ["<64 hex>"]}
}
```

A rejected message MUST leave both objects untouched, so the recorded state after a
rejection is identical to the state before it. That is the observable form of the
all-or-nothing rule in §3 step 2.
