# Chaincraft Wire Protocol — v1 (Level 0)

**Release:** 1.3.0

**Status:** Current
**Protocol version on the wire:** `1`
**Scope:** Level 0 only. Everything an implementation MUST do byte-for-byte to join a
Chaincraft mesh. Nothing else.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be interpreted as in
RFC 2119.

---

## 0. What this document is for

Three independent implementations (Python, Rust, TypeScript) must be able to form a
single gossip mesh. This document is the only contract between them. It is deliberately
small: a conforming Level 0 core is a few hundred lines per language.

An implementation is **Level 0 conformant** when it passes every vector in
`conformance/vectors/` and completes the live interop matrix in `conformance/runner/`.

Anything not specified here is out of scope **for this document**, not optional. It is
covered by `SPEC/semantics-v1.md` (Level 1) or `SPEC/features.yaml` (Level 2). See §10.

---

## 1. Canonical JSON

Every hash, signature and frame in this protocol is computed over **canonical JSON**.
Non-canonical serialization is the single largest source of silent cross-implementation
failure: it produces no error, only messages that quietly never match.

Canonical form follows RFC 8785 (JCS) with one restriction stated in §1.3.

### 1.1 Rules

1. **No insignificant whitespace.** Item separator is `,` (U+002C). Key/value separator
   is `:` (U+003A). No spaces or newlines anywhere outside string literals.
2. **Object keys sorted** ascending by Unicode code point of the key string.
   Duplicate keys MUST be rejected on parse.
3. **Output encoding is UTF-8.** Non-ASCII characters MUST be emitted literally, never
   as `\uXXXX` escapes.
4. **String escaping** uses the shortest form permitted by RFC 8259:
   - `"` → `\"`, `\` → `\\`
   - U+0008 → `\b`, U+0009 → `\t`, U+000A → `\n`, U+000C → `\f`, U+000D → `\r`
   - All other code points below U+0020 → `\u00xx` with **lowercase** hex digits
   - `/` MUST NOT be escaped
5. **Booleans and null** are `true`, `false`, `null`.
6. **Arrays** preserve their order. Order is significant.

#### 1.1.1 Code point order is not UTF-16 code unit order

Rule 2 says code point order, and that is not the same as sorting UTF-16 strings with a
default comparator. A key in the astral planes encodes as a surrogate pair beginning at
U+D800, which sorts *below* the BMP range U+E000–U+FFFF by code unit and *above* it by
code point:

| Keys | Code point order (correct) | UTF-16 code unit order (wrong) |
|---|---|---|
| `"\uE000"`, `"\u{10000}"` | `\uE000` then `\u{10000}` | `\u{10000}` then `\uE000` |

Python's `str` comparison and Rust's UTF-8 byte comparison both give code point order.
JavaScript's `Array.prototype.sort()` default comparator does not, so a JavaScript
implementation MUST compare by code point explicitly.

The vector `astral plane key ordering` pins this.

### 1.2 Numbers

Integers only, serialized with no leading `+`, no leading zeros, no exponent, and `-0`
normalized to `0`.

Permitted range is the IEEE-754 double-safe integer range:

```
-9007199254740991 .. 9007199254740991      (-(2^53 - 1) .. 2^53 - 1)
```

### 1.3 Restriction: no floating point in v1

Floating-point numbers MUST NOT appear anywhere in a canonical payload. An
implementation encountering one MUST reject the value.

*Rationale.* Cross-language agreement on shortest-round-trip float formatting is the
hardest part of JCS and delivers no value to a gossip substrate. Applications needing
fractional values MUST encode them as integers with a fixed scale (for example
millisatoshis) or as strings. This restriction may be lifted in a later version.

#### 1.3.1 The restriction is lexical, not only numeric

A parser MUST reject any JSON number **token** containing a fraction or an exponent,
**even when its value is mathematically an integer**. `1.0`, `1e3` and `-0.0` are all
rejected, despite denoting 1, 1000 and 0.

This is stated separately because it is not reachable by inspecting the parsed value in
every language. A parser that produces one numeric type — notably JavaScript's
`JSON.parse`, which yields `1000` for the token `1e3` — has already destroyed the
information needed to apply §1.3 and is therefore **non-conformant on its own**. Such an
implementation MUST inspect the number tokens lexically, which in practice means parsing
canonical JSON with its own parser rather than the platform's.

Languages that preserve the distinction, such as Python's `float` and Rust's
`serde_json::Number`, satisfy this rule by rejecting any non-integer parsed value.

Two vectors pin this: `integer-valued float` and `exponent` in
`conformance/vectors/canonical-json.json`.

### 1.4 Nesting limit

A value nested more than **100** levels deep MUST be rejected, on both encode and parse.
Arrays and objects each count as one level.

This is a normative limit rather than an implementation detail because an unspecified one
diverges: a payload 200 levels deep would be accepted by an implementation with no limit
and rejected by one with a limit, and the two would disagree about a message's validity
while both believed they were conformant. The limit also bounds recursion depth in a
recursive-descent parser fed hostile input.

### 1.5 Reference behaviour per language

All three produce byte-identical output on the permitted subset:

| Language | Encoding | Parsing |
|---|---|---|
| Python | `json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` | `json.loads` with an `object_pairs_hook` rejecting duplicate keys |
| Rust | `serde_json::to_string(&v)` where `v: serde_json::Value` (default `BTreeMap` ordering) | `serde_json`, rejecting any non-integer `Number` |
| TypeScript | recursive canonicalizer with an explicit code point comparator (§1.1.1) | **its own parser** — `JSON.parse` cannot satisfy §1.3.1 or duplicate-key rejection |

Implementations MUST NOT rely on the table above without also passing
`conformance/vectors/canonical-json.json`, which pins the exact bytes.

Note the asymmetry: encoding is a one-liner in two of the three languages, while parsing
needs care in all three. Every entry in the parsing column exists because the platform
default is wrong in some way — silently keeping the last duplicate key, or normalizing a
float token to an integer.

---

## 2. Payload digest

The **payload digest** identifies a message. It is content-addressed:

```
digest = lowercase_hex( SHA-256( canonical_json(data) ) )
```

`data` is the application payload, not the envelope. The digest is a 64-character
lowercase hex string.

Three consequences, all intentional:

- **The digest is stable across re-serialization.** A relaying node may rebuild the
  envelope freely without breaking deduplication downstream. This removes the
  "must relay bytes verbatim" fragility.
- **The digest is independent of transport settings.** Compression, framing and
  transport choice do not affect it.
- **Identical payloads are the same message.** Two messages with equal `data` share a
  digest and are deduplicated to one. An application requiring distinguishable
  messages with otherwise-equal content MUST include a nonce or timestamp field
  inside `data`.

---

## 3. Envelope

Every frame on the wire is exactly one envelope, serialized as canonical JSON.

```json
{"alg":"schnorr","data":{"n":1},"id":"<64 hex>","pk":"<64 hex>","sig":"<128 hex>","ts":1757430000000,"type":"app.counter","v":1}
```

### 3.1 Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `v` | integer | yes | Protocol version. MUST be `1`. |
| `type` | string | yes | Message type. See §3.2. 1–64 chars, `[a-z0-9._-]`. |
| `data` | any | yes | Application payload. MUST be canonical-JSON representable. |
| `id` | string | yes | Payload digest (§2). 64 lowercase hex. |
| `ts` | integer | yes | Unix time in **milliseconds**, UTC. |
| `sig` | string | no | Signature over `id`. 128 lowercase hex. |
| `pk` | string | no | Public key of the signer. 64 lowercase hex. |
| `alg` | string | no | `"schnorr"` or `"ed25519"`. |

No other fields are permitted. An envelope carrying an unknown field MUST be rejected.

Since keys are sorted, the on-wire field order is always:
`alg, data, id, pk, sig, ts, type, v`.

### 3.2 The `type` namespace

- `ctl.*` — mesh control, defined in §5. Implementations MUST NOT invent new
  `ctl.*` types outside this spec. Never relayed.
- `link.*` — protocol control. Any protocol may use it. Delivered to that
  protocol with the peer address of the link it arrived on. Never relayed.
- Everything else — gossip. Convention is `app.<name>`. A node relays it.

### 3.3 Validation order

A receiver MUST validate in this order and reject on the first failure, because the
checks are ordered cheapest-first and signature verification is the only expensive step:

1. Frame length within limits (§4).
2. Body parses as JSON, with no duplicate object keys.
3. Field set is exactly the permitted set; `v == 1`.
4. Field types and formats are as tabled in §3.1.
5. `data` is canonical-JSON representable (no floats, integers in range).
6. `id == sha256(canonical_json(data))`.
7. If `sig` is present: `pk` and `alg` are present, and the signature verifies (§6).

Steps 1–6 are pure and side-effect free.

### 3.4 Timestamps

`ts` is self-asserted and unverifiable. It MUST NOT be used for ordering or for
deduplication. Implementations SHOULD reject envelopes with `ts` more than 300000 ms
(5 minutes) in the future, and SHOULD NOT reject old timestamps — backfill is legitimate.

---

## 4. Framing and transport

### 4.1 TCP (baseline — MUST implement)

```
+-----------------+---------------------------+
| length (4 bytes)| canonical JSON body       |
| big-endian u32  | exactly `length` bytes    |
+-----------------+---------------------------+
```

- `length` counts body bytes only, excluding the prefix.
- Maximum body length is **16777216** bytes (16 MiB). A receiver MUST reject a
  declared length above this without reading the body.
- A length of `0` is invalid.
- A connection MAY carry multiple consecutive frames. A receiver MUST handle short
  reads and reassemble.

### 4.2 UDP (optional — MAY implement)

One envelope per datagram, no length prefix. Maximum body **65507** bytes. An
implementation supporting UDP MUST still implement TCP, and MUST NOT assume a peer
supports UDP unless advertised in `ctl.hello` (§5.1).

### 4.3 Compression

**None at Level 0.** Compression changes the bytes hashed by naive implementations and
buys little on JSON of this size. Any future compression MUST be negotiated in
`ctl.hello` and MUST NOT alter the payload digest.

---

## 5. Control messages

The control path is an ordinary envelope whose `type` starts with `ctl.` or
`link.`. It is never stored in the application message set and never relayed.
`ctl.*` is handled by the mesh. `link.*` is delivered to the application with
the peer address and no other context. Gossip is every other type: it is
recorded, deduplicated, and relayed. Envelope `v` stays 1. No new field is
added; the path is the type prefix.

### 5.1 `ctl.hello` — version and capability negotiation

Sent as the first frame on every new connection. Both sides send it.

```json
{"caps":["gossip","digest-sync","udp"],"impl":"py-chaincraft/1.0.0","listen":"10.0.0.2:9735","v":1}
```

`data` fields:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `v` | integer | yes | Highest protocol version supported. |
| `impl` | string | yes | `<name>/<semver>`, free-form, for diagnostics only. |
| `caps` | array of string | yes | Capabilities, **sorted** (see below). Unknown entries MUST be ignored. |
| `listen` | string | no | `host:port` this node accepts connections on. |

A peer advertising a `v` this node cannot speak MUST be disconnected cleanly rather
than silently ignored.

Defined capabilities at v1: `gossip`, `digest-sync`, `udp`.

`caps` MUST be sorted ascending by code point and MUST NOT contain duplicates. Canonical
JSON sorts object keys but preserves array order (§1.1 rule 6), so without this rule the
same capability set announced in a different order would produce a different payload
digest — and the digest is the message identity (§2). Sorting makes an identical
capability set an identical message.

A receiver MUST NOT reject an unsorted `caps`; it is a sender-side rule. Ignoring the
order on receipt keeps a strict sender interoperating with a sloppy one.

### 5.2 `ctl.peers.request` / `ctl.peers` — peer exchange

Request carries `data: {}`. Response:

```json
{"peers":["10.0.0.2:9735","10.0.0.3:9735"]}
```

Entries are `host:port`. A receiver MUST bound how many it accepts and MUST NOT
connect to entries it did not solicit.

### 5.3 `ctl.digest.request` / `ctl.digest` — state digest exchange

Request:

```json
{"object":"BalanceLedger"}
```

Response:

```json
{"digest":"<64 hex>","frontier":["<64 hex>"],"object":"BalanceLedger"}
```

`frontier` carries the multi-head digests defined at Level 1 and MAY be an empty array.

### 5.4 `ctl.messages.request` / `ctl.messages` — backfill

Request:

```json
{"object":"BalanceLedger","since":"<64 hex>"}
```

Response carries up to `limit` envelopes the responder holds after `since`:

```json
{"messages":[{...envelope...}],"object":"BalanceLedger"}
```

A responder MUST cap the response to fit §4.1 limits and MAY return a partial set; the
requester repeats with an updated `since`.

---

## 6. Signatures

Signatures are **optional at Level 0**. A conformant implementation MUST be able to
verify both algorithms below, and MUST be able to produce at least one.

The signed message is the **32 raw bytes** obtained by hex-decoding `id`. It is already
a SHA-256 digest and MUST NOT be hashed again.

| `alg` | Scheme | Public key | Signature |
|---|---|---|---|
| `schnorr` | BIP-340 over secp256k1 | 32-byte x-only, 64 hex | 64 bytes, 128 hex |
| `ed25519` | RFC 8032 Ed25519 | 32 bytes, 64 hex | 64 bytes, 128 hex |

Verification MUST be failure-safe: malformed keys or signatures return "invalid",
never an exception propagated into the receive path.

---

## 7. Deduplication and relay

A node maintains a bounded set of seen payload digests.

### 7.1 Rules

- On receiving an envelope whose `id` is already in the set, a node MUST NOT re-process
  or re-broadcast it. This terminates gossip loops.
- An envelope whose `id` is absent is processed, and its `id` is then added to the set.
- A node MAY re-serialize an envelope before relaying. The digest is unaffected (§2), so
  a relayed copy is still recognized as a duplicate downstream.
- Control-path messages (`ctl.*` and `link.*`) are point-to-point: they are never
  added to the set, never deduplicated by digest, and never relayed. The same
  `link.*` payload may arrive twice on one connection and both are delivered.

### 7.2 Capacity and eviction

The set holds at most **100000** digests. When full, insertion evicts the digest
inserted longest ago. Re-seeing a digest does **not** refresh its position.

Both numbers are normative rather than left to the implementer, because both are
observable. Two nodes with different capacities disagree about whether an old message is
a duplicate; and a node that refreshed position on re-seeing would retain a different
set than one that did not, after the same message sequence. FIFO by first insertion is
also the cheapest rule to express in all three languages, since Python's `dict`,
JavaScript's `Set` and Rust's `IndexMap` already preserve insertion order and leave it
undisturbed on a repeat insert.

`conformance/vectors/dedup.json` pins the sequence behaviour, including eviction.

---

## 8. Error handling

Level 0 defines no error frames. A node encountering an invalid frame MUST close the
connection. Rationale: a peer sending malformed frames is either broken or hostile, and
in either case negotiation is not useful. Application-level error reporting belongs to
Level 2.

---

## 9. Conformance

An implementation claiming Level 0 conformance MUST:

1. Pass every vector in `conformance/vectors/`.
2. Complete the live matrix in `conformance/runner/` against both other
   implementations, in both directions.
3. Advertise its version honestly in `ctl.hello`.

Vectors are generated from the Python reference implementation by
`conformance/generate_vectors.py` and are checked into the repository. Regenerating
them is a deliberate, reviewable act: a changed vector file in a diff means the wire
protocol changed.

---

## 10. Out of scope for this document

Consensus, ledger models, fee policies, mempool behaviour, storage backends, CLI
surface, async model, retry and backoff policy, NAT traversal, and the application
layer.

Out of scope **here** does not mean optional. Everything above is covered by the
parity commitment: it is specified in `SPEC/features/`, registered in
`SPEC/features.yaml`, and required in all three implementations. This document is
narrow so it can be frozen, not because the rest is discretionary. See `ROADMAP.md`.

The only latitude at Level 0 is in mechanism, never in behaviour: which secp256k1
library you bind, how you schedule I/O, how you represent errors. Two conformant
nodes produce identical bytes regardless.
