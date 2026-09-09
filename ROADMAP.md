# Chaincraft — Full Parity Roadmap

Three implementations — Python, Rust, TypeScript — held at **100% feature parity**.

This document defines what that commitment means, why it is achievable, and the
machinery that enforces it. The enforcement is automated: parity is a CI gate, not a
promise.

---

## 1. The commitment

> Every capability of Chaincraft exists in all three implementations, with identical
> observable behaviour, verified by shared conformance vectors on every pull request.

### What parity means

- **Wire parity.** Byte-identical output for the same input. Any node talks to any node.
- **Semantic parity.** The same message sequence produces the same state and the same
  digests in all three.
- **Feature parity.** Every consensus algorithm, ledger model, fee policy, mempool
  behaviour and protocol exists in all three.
- **Behavioural parity.** The same inputs produce the same outputs, the same rejections,
  and the same error *classes*.

### What parity does not mean

Parity is of **capability and behaviour**, not of syntax. Forcing one language to imitate
another's idiom produces code that is bad in all three. These differ freely:

| Free to differ | Example |
|---|---|
| Naming convention | `add_message` / `addMessage` / `add_message` |
| Async model | `asyncio` / `tokio` / promises |
| Error representation | exceptions / `Result<T, E>` / thrown `Error` subclasses |
| Memory and ownership | GC / borrow checker / GC |
| Package layout | modules / crates / ESM entry points |
| Native optimizations | `coincurve` / `secp256k1` crate / WebCrypto |

The rule: a user should be able to describe a behaviour in prose and find it in all
three. They should not expect to copy code between them.

---

## 2. Why this is tractable

Full parity across N languages usually fails because drift is invisible until someone
trips over it, and because porting is manual. Both are now solvable:

1. **The spec is the source of truth, not any implementation.** Features are specified
   in `SPEC/` before they are written. Three implementations then target a document, not
   each other.
2. **Conformance vectors make behaviour executable.** Every feature ships golden vectors.
   A divergence is a red test on a pull request, not a bug report six months later.
3. **A machine-readable parity registry.** `SPEC/features.yaml` records every feature and
   its status per language. Drift becomes a queryable fact.
4. **A CI gate that fails on drift.** `tools/parity_check.py` cross-checks the registry
   against what each implementation actually reports, and enforces the porting deadline.
5. **Coding agents do the porting.** A parity gap opens a labelled GitHub issue and
   dispatches an agent with the spec section, the vectors and the reference
   implementation as context. Porting a specified, vector-covered feature into a second
   language is exactly the kind of bounded work agents do well.
6. **`AGENTS.md` keeps agents and humans on the same contract.** Every contributor, human
   or otherwise, reads the same rules.

The honest version: parity has a real cost, and it is paid by automating the porting and
detecting drift instantly. Without items 3 through 6 this commitment would not survive
contact with a busy month.

---

## 3. The three levels

Levels no longer describe *how much* compatibility we want — all three are mandatory.
They now describe **how each layer is verified**, because the verification technique
differs.

### Level 0 — Wire parity · verified byte-for-byte

**Spec:** `SPEC/wire-v1.md` · **Gate:** golden vectors + live 3×3 mesh matrix

Canonical JSON, payload digest, envelope, framing, control messages, version
negotiation, signatures.

Frozen and versioned. A change here is a protocol version bump and appears in the diff
as a changed vector file.

### Level 1 — Semantic parity · verified by replay

**Spec:** `SPEC/semantics-v1.md` · **Gate:** replay vectors, no networking

Apply pipeline, `StateMemento` normalization, merkelized digests, replacement
tie-breaking. Each implementation replays a fixed message sequence and must produce
identical digests.

### Level 2 — Feature parity · verified by the parity registry

**Spec:** `SPEC/features.yaml` plus per-feature specs · **Gate:** `tools/parity_check.py`

Consensus algorithms, ledger models, fee policies, mempool, discovery, storage
semantics, CLI capabilities. Every feature carries an entry in the registry and a status
per language.

This is the level that changed. It was previously "free to diverge"; it is now the level
requiring the most machinery, which is why sections 4 and 5 exist.

---

## 4. The parity machine

### 4.1 Feature registry

`SPEC/features.yaml` is the single record of what exists:

```yaml
- id: consensus.pow
  level: 2
  spec: SPEC/features/consensus-pow.md
  summary: Proof-of-work consensus object
  vectors: conformance/vectors/consensus-pow.json
  status:
    python:     { state: implemented, since: "2026-09-09" }
    rust:       { state: implemented, since: "2026-09-14" }
    typescript: { state: in-progress, since: "2026-09-09", issue: 42 }
```

Four states:

| State | Meaning |
|---|---|
| `implemented` | Present, vectors passing |
| `in-progress` | Being ported; `issue` is required |
| `planned` | Accepted, not started |
| `exempt` | Genuinely inapplicable; `reason` is required and reviewed |

`exempt` is the pressure valve, and it is narrow. It covers *implementation mechanisms*
that cannot cross a language boundary — a WebCrypto backend has no meaning in Rust, a
`multiprocessing` fallback has none in TypeScript. It never covers a capability. If a
user can observe the difference, it is not exempt.

### 4.2 Self-reporting manifests

Each implementation exports the feature IDs it claims:

| Language | Command |
|---|---|
| Python | `python -m chaincraft_core.features` |
| Rust | `cargo run --bin features` |
| TypeScript | `npm run --silent features` |

`tools/parity_check.py` runs all three and diffs them against the registry. A registry
claiming a feature the implementation does not report is a hard failure. This is what
stops the registry from becoming decorative.

### 4.3 The gate

`tools/parity_check.py` fails a pull request when:

1. A registry entry disagrees with an implementation's manifest.
2. A feature is `implemented` somewhere and `planned` elsewhere with no tracking issue.
3. A feature has been non-`implemented` in some language for longer than the grace
   period, currently **14 days**.
4. An `exempt` entry has no reason, or the reason is unreviewed.
5. A feature has no vectors and is not Level 2 documentation-only.

### 4.4 The grace period

A feature may land in one language first. It then has **14 days** to reach the other
two. This exists because requiring three implementations in a single commit would stop
anyone from prototyping.

On merge of a feature that is not yet universal, CI opens a `parity-gap` issue per
missing language and dispatches a coding agent. At day 7 the issue is escalated. At
day 14 the parity gate turns red on `main` and blocks releases until closed.

### 4.5 Agent-driven porting

The port task is well-suited to automation because everything it needs already exists:
a spec section, golden vectors, a reference implementation, and a definition of done
(vectors pass, manifest updated, registry updated).

`.github/workflows/parity-dispatch.yml` supplies exactly that context. The agent opens a
pull request against the gap issue. **Agent output is reviewed like any other pull
request** — the vectors are the objective check, human review is the judgement call.

---

## 5. Staged plan

### Stage 1 — Freeze the wire contract ✅

`SPEC/wire-v1.md` and `SPEC/semantics-v1.md`, resolving the four known divergences:

| Divergence | Resolution in v1 |
|---|---|
| Non-canonical JSON in both implementations | RFC 8785 subset, no floats (`wire-v1.md` §1) |
| Python hashes compressed bytes; Rust hashes envelope fields | Hash canonical `data` only (§2) |
| Bare payload vs full envelope | Envelope, content-addressed so re-serialization is safe (§3) |
| No protocol version anywhere | `v` field plus `ctl.hello` negotiation (§5.1) |

### Stage 2 — Python reference core ✅

`python/chaincraft_core/` — Level 0 and Level 1 complete, 260 tests passing.

### Stage 3 — Parity machinery ✅

The gate must exist before the second implementation, not after. Building it later means
retrofitting a registry onto code that has already drifted.

- [x] `SPEC/features.yaml`
- [x] `tools/parity_check.py`
- [x] Python feature manifest
- [x] `AGENTS.md` at root and per package
- [x] CI workflows: conformance, parity gate, dispatch
- [x] Golden vectors for all Level 0 features — 82 cases across 6 files

### Stage 4 — TypeScript core ✅

`typescript/src/` — Level 0 and Level 1 complete, 173 tests passing.

Written from `SPEC/` alone, without reading the Python source. The premise was that if a
fresh implementation cannot be built from the document, the document is wrong and gets
fixed. It found five defects, all now fixed in the spec and pinned by vectors:

| Defect | Why it mattered | Fix |
|---|---|---|
| §0 declared everything unspecified free to differ | Directly contradicted the parity commitment in §10 | §0 rewritten |
| The no-float rule was unenforceable in JavaScript | `JSON.parse('1e3')` returns `1000`, so the `exponent` vector was unsatisfiable | §1.3.1 makes the rule lexical; TypeScript ships its own parser |
| "Sorted by code point" read as satisfiable by a default sort | UTF-16 code unit order disagrees for astral keys | §1.1.1 states the difference; vector added |
| No nesting limit | Python rejected past depth 100; a fresh implementation would not | §1.4 fixes it at 100 |
| §7 had no capacity or eviction rule — and no implementation in any language | Python's manifest claimed `wire.dedup` while no such module existed | §7.2 specifies both; implemented in Python and TypeScript, with `dedup.json` |

The last one is the most instructive. The parity gate compares the registry against each
manifest, but a manifest is a self-report: it caught nothing, because Python's claim was
internally consistent and merely false. Writing a second implementation is what exposed
it. A gate can enforce agreement between documents; only a second implementation tests
whether the documents describe anything real.

### Stage 5 — Rust core ✅

`rust/` — Level 0 and Level 1 complete, 22 conformance tests covering the 159 shared
cases. Written from `SPEC/`, not from the previous `chaincraft-rust` crate.

### Stage 6 — Live interop matrix ✅

Three TCP nodes, one per language, connected as a triangle. Each sends `app.interop`;
every node ends with the same three payload digests. Dedup and a `ctl.hello` version
mismatch are checked on the live sockets.

    python3 conformance/runner/run_interop.py

### Stage 7 — Level 1 replay parity ✅

Pipeline and memento vectors through each object registry; identical digests.

- [x] `SPEC/semantics-v1.md` §8 conformance objects
- [x] Python / TypeScript / Rust replay against `memento.json` and `pipeline.json`

### Stage 8 — Level 2 backfill

The large stage. Python currently carries roughly 145 modules against Rust's 32, so most
entries start `implemented` in Python and `planned` elsewhere. Work in dependency order,
one registry entry at a time, agent-ported and human-reviewed:

1. `crypto.*` — primitives, VDF, VRF ✅ (`crypto.ecdsa`, `crypto.vdf`, `crypto.vrf`)
2. `object.*` — shared object model, mementos
3. `discovery.*` — peer discovery, gossip policy ✅ (`discovery.peer`, `discovery.local`)
4. `consensus.*` — PoW, PoS, PBFT examples ✅ (`consensus.pow`, `consensus.pos`, `consensus.pbft`)
5. `ledger.*` — balance and UTXO models
6. `mempool.*`, `fees.*`
7. `storage.*` — persistence semantics
8. `cli.*` — command surface

The grace period is suspended for Stage 8 backfill entries, which carry explicit
milestone dates instead. Applying a 14-day clock to a pre-existing 113-module gap would
paint CI red permanently and train everyone to ignore it.

### Stage 9 — Prove it with `nostraft`

A mixed Rust/Python/TypeScript `nostraft` relay mesh. The demo that makes the whole
exercise concrete.

---

## 6. Versioning

Full parity implies **lockstep releases**. All three packages carry the same version and
release together:

```
chaincraft-core (PyPI)   1.2.0
chaincraft-core (crates) 1.2.0
@chaincraft/core (npm)   1.2.0
```

A single tag `v1.2.0` releases all three. A language cannot ship a minor version alone,
because a minor version means a new feature, and a new feature means all three have it.

Patch releases MAY be per-language for language-specific bug fixes, tagged
`v1.2.1-python`.

The wire protocol keeps its own tag, `wire-v1`, since it changes far less often.

`nostraft` stays **outside** this repository. It is an application consuming
`chaincraft-core` as a dependency.

---

## 7. Working rules

1. **Spec first.** A feature is specified in `SPEC/` before implementation. Pull requests
   adding behaviour with no spec entry are closed.
2. **Vectors with the first implementation.** The language that implements first writes
   the vectors. Porting without vectors is guesswork.
3. **Registry updated in the same pull request.** `SPEC/features.yaml` is never updated
   retroactively.
4. **Atomic cross-language changes.** A spec change plus three implementations lands in
   one pull request when possible. This is why it is a monorepo.
5. **Changed vectors need justification.** A diff under `conformance/vectors/` requires
   an explicit explanation in the pull request description.
6. **`exempt` needs a reviewer.** Self-approved exemptions are how parity commitments
   quietly die.
7. **Path-filtered CI, unfiltered parity gate.** A TypeScript-only pull request skips the
   Rust suite but never skips `parity_check`.

See `AGENTS.md` for the contributor contract, human and agent alike.
