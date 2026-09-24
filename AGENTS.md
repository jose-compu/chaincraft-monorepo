# AGENTS.md — Contributor contract

Read this before changing anything. It applies to human and agent contributors equally.

This repository holds three implementations of Chaincraft — Python, Rust and TypeScript
— committed to **100% feature parity**. Most rules below exist to protect that
commitment, because parity is easy to state and easy to lose.

---

## 1. Repository layout

```
SPEC/            Normative specifications. The source of truth.
  wire-v1.md       Level 0 — wire protocol, byte-exact
  semantics-v1.md  Level 1 — object and pipeline semantics
  features.yaml    Level 2 — the parity registry
  release.yaml     Spec release, matched to the three package versions
  features/        Per-feature specs
conformance/     Shared golden vectors and the live interop runner
  vectors/         Committed test vectors, generated from the reference impl
  runner/          Cross-language live mesh tests
python/          Reference implementation
rust/            Rust implementation
typescript/      TypeScript implementation
tools/           parity_check.py and other repo-level tooling
```

---

## 2. The five rules

### Rule 1 — The spec is the source of truth, never an implementation

Behaviour is defined in `SPEC/`. Implementations target the document, not each other.

When implementation and spec disagree, **the spec wins and the implementation is a bug**
— unless the spec is wrong, in which case fix the spec first, in its own pull request,
then fix all three implementations.

Never resolve ambiguity by reading another implementation's source. If the document is
ambiguous, the document is defective. Say so and fix it.

### Rule 2 — Every feature exists in all three languages

There is no "Python-only" or "Rust-only" feature. A feature landing in one language
starts a **14-day clock** to reach the other two (§5).

The only exception is `exempt` in the registry, which covers implementation mechanisms
that cannot cross a language boundary — a WebCrypto backend has no meaning in Rust. It
never covers a capability a user can observe. `exempt` requires a written reason and a
human reviewer.

### Rule 3 — Parity is of behaviour, not of syntax

Write idiomatic code in each language. Do not transliterate.

| Match exactly | Follow local idiom |
|---|---|
| Observable behaviour | Naming convention |
| Accept/reject decisions | Async model |
| Serialized bytes | Error representation |
| Digests and state transitions | Module layout |
| Error *classes* | Error *types* and messages |

Rust returning `Result<T, ProtocolError>` where Python raises `ProtocolError` is correct
parity. Rust returning `Ok(())` where Python raises is a parity bug.

### Rule 4 — Vectors are written with the first implementation

The language that implements a feature first writes its golden vectors into
`conformance/vectors/`. Porting a feature with no vectors is guesswork, and guesswork is
how three implementations drift while all their tests stay green.

### Rule 5 — The registry is updated in the same pull request

`SPEC/features.yaml` reflects reality as of the merge commit. Never update it
retroactively, never leave it for a follow-up.

`SPEC/release.yaml` is the spec release. It must equal the version in
`python/pyproject.toml`, `rust/Cargo.toml`, and `typescript/package.json`.
Every markdown file under `SPEC/` carries `**Release:**` with that version
and is listed in `release.yaml`. The parity gate fails when they diverge.
The envelope protocol number is `wire_protocol` in that file. It is not the
spec release. A normative change that ships under a new release number updates
the stamp in the same pull request.

---

## 3. Adding a new feature

1. **Specify.** Write `SPEC/features/<id>.md`. Define observable behaviour, inputs,
   outputs, rejection conditions and edge cases. Enough that someone can implement from
   the document alone.
2. **Register.** Add the entry to `SPEC/features.yaml`, `planned` for all three.
3. **Implement once.** Any language. Write vectors alongside.
4. **Add to the manifest.** Register the feature ID in that language's feature manifest
   (`python/chaincraft_core/features.py`, `rust/src/features.rs`,
   `typescript/src/features.ts`).
5. **Update the registry** to `implemented` for that language.
6. **Open gap issues.** CI does this automatically on merge, one per missing language.
7. **Port within 14 days.**

Steps 1 and 2 are not optional overhead. They are what makes step 7 an agent-sized task
instead of a research project.

## 4. Porting an existing feature

You will usually arrive here from a `parity-gap` issue, which names the feature ID,
target language, spec section, vectors and reference implementation.

1. Read the spec section. **Read the reference implementation only for clarification**,
   never as something to transliterate.
2. Implement idiomatically in the target language.
3. Run the vectors. They must pass unmodified.
   **If a vector fails, the default assumption is that your port is wrong.** A vector is
   only wrong if you can demonstrate it contradicts the spec — and then the fix is a
   separate pull request touching the spec, the vectors and all three implementations.
4. Add the feature ID to the language's manifest.
5. Update `SPEC/features.yaml` to `implemented`.
6. Run `python3 tools/parity_check.py` locally before opening the pull request.

---

## 5. The parity gate

`tools/parity_check.py` runs on every pull request and fails when:

1. The registry claims a feature an implementation's manifest does not report.
2. A feature is `implemented` somewhere and `planned` elsewhere with no tracking issue.
3. A feature has been non-`implemented` in a language for more than **14 days**.
4. An `exempt` entry has no reason.
5. A feature has vectors declared that do not exist.

Run it locally:

```bash
python3 tools/parity_check.py            # full check
python3 tools/parity_check.py --summary  # parity table
python3 tools/parity_check.py --gaps     # open gaps only
```

The gate is never skipped by path filters. A TypeScript-only pull request skips the Rust
test suite but still runs `parity_check`.

---

## 6. Commands

```bash
# Python
cd python && python3 -m pytest tests/ -v

# Rust
cd rust && cargo test --all-features

# TypeScript
cd typescript && npm test

# Conformance vectors, all languages
python3 conformance/run_all.py

# Live 3x3 interop matrix
python3 conformance/runner/run_interop.py
python3 conformance/runner/run_bittorrent.py

# Regenerate vectors — deliberate act, see section 7
python3 conformance/generate_vectors.py
```

---

## 7. Changing the wire protocol

Rare and expensive. Everything in `SPEC/wire-v1.md` is frozen.

A changed file under `conformance/vectors/` means the protocol changed. If that appears
in a diff and the pull request description does not explain it, the pull request is
rejected on sight.

Protocol changes require: a new version number, a spec update, `ctl.hello` negotiation
for the new version, all three implementations in the same pull request, and a
compatibility note. Do not regenerate vectors to make a failing test pass. That converts
a caught bug into a silent protocol fork.

---

## 8. Git and pull requests

- Never commit directly to `main`.
- One logical change per pull request.
- **Never attribute authorship or co-authorship to an AI, an agent, Cursor, Claude or
  any model.** No `Co-authored-by` trailers naming a tool, no "generated by" notes, and
  no "Made with Cursor" or any similar tool footer. This covers commits, code comments,
  pull request titles and descriptions, and issue titles, bodies, and comments. Commits
  are authored by the human who owns the change.
- Do not create summary markdown files describing what a change did. The pull request
  description is the summary.

Pull request description must state: what changed, which spec sections apply, which
feature IDs are affected, and — if `conformance/vectors/` changed — why.

### GitHub workflow

Every behaviour change follows this order.

1. **Issue.** Open a GitHub issue before the branch. The title is the feature id or the bug. The body states the observable behaviour, the spec section to add or change, the vector file, and the three languages.
2. **Branch.** Create the branch from current `main`. Never commit on `main`.
3. **Spec, code, vectors.** One change. A new feature lands in all three languages together, with `SPEC/features.yaml` updated in that branch.
4. **Check.** Run `python3 tools/parity_check.py` and the language suites. When the feature has performance tests, run them so the timings are visible, and keep them inside the suite.
5. **Pull request.** Push the branch and open a pull request that links the issue (`Fixes #N`). The description states what changed, which spec sections apply, which feature IDs are affected, and why any file under `conformance/vectors/` changed.
6. **Review.** Read the spec against the diff. CI must be green. Answer review comments with new commits.
7. **Merge.** Use the repository default. The closing keyword on the pull request closes the issue.

---

## 9. Code style

Match the surrounding code. Comment to state a constraint the code cannot express, not
to narrate what the next line does or to justify the change to a reviewer.

Do not add comments referencing the porting process, the issue number, or another
language's implementation. `# same as the Rust version` is meaningless to the next
reader and wrong the moment either side changes.

| Language | Formatter | Linter |
|---|---|---|
| Python | `black` | `ruff` |
| Rust | `cargo fmt` | `cargo clippy -- -D warnings` |
| TypeScript | — | `tsc --noEmit` under `strict` |

---

## 10. Definition of done

A change is complete when:

- [ ] Spec written or updated, if behaviour changed
- [ ] Implemented in the target language, idiomatically
- [ ] Vectors written (first implementation) or passing unmodified (port)
- [ ] Feature ID present in the language's manifest
- [ ] `SPEC/features.yaml` updated in this same pull request
- [ ] `SPEC/release.yaml` matches the package versions, and every spec file carries that release
- [ ] `python3 tools/parity_check.py` passes
- [ ] Language test suite passes
- [ ] Gap issues opened for languages not yet ported
- [ ] GitHub issue open, and the pull request links it
- [ ] No AI or tool attribution in the change, its commits, its pull request, or its issues
