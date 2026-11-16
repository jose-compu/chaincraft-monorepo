# AGENTS.md — TypeScript implementation

Read the root `AGENTS.md` first. This file covers only what is specific to `typescript/`.

**Status: Level 0, Level 1, and Level 2 crypto (`ecdsa`/`vdf`/`vrf`) complete.** Stage 8 in `ROADMAP.md`.

## Role: the spec's proving ground

This implementation was written **from `SPEC/` alone**, without reading the Python
source. It is the only greenfield implementation, which makes it the real test of whether
the specification is complete.

Keep working that way. If you cannot implement something from the document, that is a
defect in the document. Fix it in `SPEC/` and add a vector. Do not resolve the ambiguity
by reading `python/` — that hides the defect and leaves the next implementer to
rediscover it.

The exercise paid for itself. Writing this package surfaced five specification defects,
all now fixed and pinned by vectors:

| Defect | Fix |
|---|---|
| §0 said everything unspecified was free to differ, contradicting the parity commitment | §0 rewritten to point at §10 |
| The no-float rule was unenforceable in JavaScript, since `JSON.parse('1e3')` yields `1000` | §1.3.1 makes the rule lexical |
| "Sorted by code point" is not what `Array.prototype.sort()` does for astral characters | §1.1.1 states the difference |
| No nesting limit, so Python rejected at depth 100 and a fresh implementation would not | §1.4 fixes it at 100 |
| §7 deduplication had no capacity or eviction rule, and no implementation at all | §7.2 specifies both; implemented in both languages |

## Layout

```
src/
  canonical.ts   Canonical JSON, encoder and parser (wire-v1 §1, §2)
  envelope.ts    Envelope (§3)
  framing.ts     TCP framing and UDP datagrams (§4)
  control.ts     ctl.* messages (§5)
  crypto.ts      BIP-340 Schnorr, Ed25519 (§6)
  ecdsa.ts       secp256k1 ECDSA (crypto-ecdsa.md)
  vdf.ts         Sloth VDF (crypto-vdf.md)
  vrf.ts         Deterministic ECDSA VRF (crypto-vrf.md)
  discovery.ts   Address book and local-discovery policy
  consensusPow.ts    Prototype PoW object
  consensusPoa.ts    Prototype PoA object
  consensusPos.ts    Prototype PoS object
  consensusPbft.ts   Prototype PBFT object
  ledgerBalance.ts   Prototype account ledger
  ledgerUtxo.ts      Prototype UTXO ledger
  mempool.ts     Prototype transaction pool
  fees.ts        Prototype fee policy
  storage.ts     Prototype message store
  cli.ts         JSON-lines node command surface
  bittorrent.ts  Prototype BitTorrent swarm + client
  nat.ts         STUN, hole punch, and app.nat relay
  channel.ts     Address URIs and in-process loop channel
  pubsub.ts      Topic publish-subscribe (chat rooms)
  stream.ts      Append-only event log (producer lanes, range read)
  mesh.ts        TCP mesh (listen, hello, dedup, relay)
  node.ts        Wire CLI: connect / send / ids / quit
  btNode.ts      BitTorrent client on Mesh (`bt.*` commands)
  dedup.ts       Seen-digest set and relay gate (§7)
  memento.ts     StateMemento (semantics-v1 §4)
  object.ts      SharedObject contract; prototypes override receive
  pipeline.ts    Apply pipeline (§3)
  errors.ts      Error classes
  features.ts    Feature manifest
  featuresCli.ts Manifest printer for the parity gate
  index.ts       Public entry point
test/
  conformance.test.ts   The shared vectors — the real contract
  stream.perf.test.ts   app.stream apply and read throughput
  pipe.perf.test.ts     channel.pipe mesh throughput
  object.test.ts        Prototype defaults: receive, empty snapshot
  hazards.test.ts       JavaScript-specific traps
  conformanceObjects.ts Counter and Mirror fixtures (semantics-v1 §8)
```

## Commands

```bash
npm install
npm test                     # node:test over the TypeScript sources
npm run --silent features    # feature manifest, JSON on stdout
npm run lint                 # tsc --noEmit
npm run build                # tsc -p tsconfig.build.json, emits dist/
```

## Toolchain

Node **22.6+** is required for development, because the suite runs the `.ts` sources
directly through Node's built-in type stripping. That buys a test suite with no bundler,
no transpiler and no test framework: `node:test` and `node:assert` only. The cost is the
Node floor, and that trade is worth making for a reference implementation whose value is
being easy to read and verify.

The compiled output in `dist/` targets ES2022 and runs on Node 20. CI proves this rather
than assuming it — see the `typescript-dist` job.

Consequences to keep in mind:

- No `enum`, no `namespace`, no parameter properties (`constructor(private x: string)`).
  Type stripping rejects any syntax that emits code. Declare fields explicitly.
- Relative imports carry a `.ts` extension. `rewriteRelativeImportExtensions` turns them
  into `.js` on emit.

Runtime dependencies are `@noble/curves` and `@noble/hashes`, both of which run
unmodified in Node and the browser.

## Conventions

- ESM, `strict` TypeScript with `noUncheckedIndexedAccess` and
  `exactOptionalPropertyTypes`. No `any` in the public API.
- Browser support is a goal for everything except UDP.
- Errors extend `ChaincraftError`, with `CanonicalError`, `ProtocolError` and
  `FramingError` subclasses mirroring the Python classes. Parity is of error *class*,
  not of message text.
- Signature verification returns `boolean` and never throws.
- Property names are camelCase; **serialized** keys follow the shared format, which is
  snake_case. `StateMemento.canonicalDigest` serializes as `canonical_digest`. Parity is
  of bytes, not of naming.

## The three JavaScript traps

These are the places where idiomatic JavaScript silently produces non-conformant output.
Each is pinned by a vector and by a test in `test/hazards.test.ts`.

**1. `JSON.parse` cannot be used.** Two independent reasons, both silent failures:

```js
JSON.parse('1e3')            // 1000 — the float token is gone (§1.3.1)
JSON.parse('{"a":1,"a":2}')  // {a: 2} — the duplicate is gone (§1.1 rule 2)
```

`src/canonical.ts` therefore carries a recursive-descent parser that inspects number
tokens and rejects repeated keys. Do not replace it with `JSON.parse` plus a reviver; a
reviver sees values that have already lost the distinction.

**2. The default sort comparator is wrong.** `Array.prototype.sort()` orders by UTF-16
code unit, and canonical JSON requires code point order (§1.1.1). They disagree whenever
an astral-plane key meets a key in U+E000–U+FFFF:

```js
['\u{10000}', '\uE000'].sort()                    // wrong order
['\u{10000}', '\uE000'].sort(compareCodePoints)   // correct
```

Always pass `compareCodePoints`.

**3. `Number.isSafeInteger` is necessary but not sufficient.** It correctly rejects
non-integers and out-of-range values, so it is the right check when *encoding*. It cannot
catch `1.0` or `1e3` when *parsing*, because those are already integers by then. Parsing
is the parser's job — see trap 1.

## UDP

`wire.framing-udp` is registered as `exempt` for TypeScript in `SPEC/features.yaml`: raw
UDP sockets do not exist in browsers, and a Node-only subset would not be the same
capability. UDP is optional at Level 0 and advertised through `ctl.hello`, so a
TypeScript node interoperates fully over TCP. This is the only exemption in the registry
— do not add more without a reviewer.

The exemption covers the *transport*, not the framing rules. `encodeDatagram` and
`decodeDatagram` enforce the size bounds and are exercised by the shared UDP vectors,
so a future Node-only transport has a conformant base to sit on.

## The feature manifest

`npm run --silent features` must print JSON on stdout in exactly this shape, because
`tools/parity_check.py` parses it:

```json
{
  "impl": "ts-chaincraft/1.0.0",
  "language": "typescript",
  "version": "1.0.0",
  "wire_version": 1,
  "features": ["wire.canonical-json", "wire.envelope"]
}
```

Nothing else may be written to stdout. Send diagnostics to stderr, and keep `--silent` in
the script so npm's own output does not corrupt it.
