#!/usr/bin/env python3
"""Open and maintain a GitHub issue for every open parity gap.

Each issue is written to be actionable by a coding agent without further
context: it names the spec section, the vectors, the reference implementations
and the definition of done.

Deduplication is by issue title, so this is safe to run repeatedly. It never
writes back to SPEC/features.yaml — the registry is updated by the pull request
that closes the gap, not by a bot.

    python3 tools/sync_gap_issues.py --dry-run
    python3 tools/sync_gap_issues.py --repo owner/name
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from parity_check import collect_gaps, load_registry, parse_date  # noqa: E402

LABEL = "parity-gap"

MANIFEST_PATHS = {
    "python": "python/chaincraft_core/features.py",
    "rust": "rust/src/features.rs",
    "typescript": "typescript/src/features.ts",
}

TEST_COMMANDS = {
    "python": "cd python && python3 -m pytest tests/ -v",
    "rust": "cd rust && cargo test --all-features",
    "typescript": "cd typescript && npm test",
}


def title_for(gap: Dict[str, Any]) -> str:
    return f"[parity] {gap['id']} -> {gap['language']}"


def body_for(gap: Dict[str, Any], overdue_by: Optional[int]) -> str:
    language = gap["language"]
    lines: List[str] = []

    lines.append(f"`{gap['id']}` is missing in **{language}**.")
    lines.append("")
    lines.append(gap["summary"])
    lines.append("")

    lines.append("## Context")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| Feature | `{gap['id']}` |")
    lines.append(f"| Level | {gap['level']} |")
    lines.append(f"| Target language | {language} |")
    lines.append(f"| Spec | `{gap['spec']}` |")
    lines.append(f"| Vectors | {'`' + gap['vectors'] + '`' if gap['vectors'] else 'none yet — write them'} |")
    if gap["reference"]:
        refs = ", ".join(f"`{r}`" for r in gap["reference"])
        lines.append(f"| Reference implementations | {refs} |")
    if gap["legacy"]:
        lines.append(f"| Port from | {gap['legacy']} |")
    if gap["backfill"]:
        lines.append(f"| Milestone | {gap['milestone']} |")
    lines.append("")

    if overdue_by is not None and overdue_by > 0:
        lines.append(
            f"> **Overdue by {overdue_by} days.** The parity gate is failing on "
            f"`main` until this closes."
        )
        lines.append("")

    lines.append("## Task")
    lines.append("")
    lines.append(f"1. Read `{gap['spec']}`. It is the source of truth.")
    if gap["reference"]:
        lines.append(
            "2. Consult the reference implementation **only to clarify the spec**. "
            "Do not transliterate it — write idiomatic "
            f"{language}."
        )
    else:
        lines.append(
            "2. No reference implementation exists yet. Implement from the spec and "
            "write the golden vectors alongside."
        )
    lines.append(
        f"3. Implement in `{language}/`, matching observable behaviour: the same "
        "accept and reject decisions, the same bytes, the same digests."
    )
    if gap["vectors"]:
        lines.append(
            f"4. Run `{gap['vectors']}`. They must pass **unmodified**. A failing "
            "vector means the port is wrong, unless it provably contradicts the "
            "spec — and that is a separate pull request."
        )
    else:
        lines.append("4. Write vectors into `conformance/vectors/` covering accept and reject paths.")
    lines.append(f"5. Add `{gap['id']}` to `{MANIFEST_PATHS[language]}`.")
    lines.append(
        f"6. Set `status.{language}.state` to `implemented` in `SPEC/features.yaml`, "
        f"with `since` set to the merge date."
    )
    lines.append("")

    lines.append("## Definition of done")
    lines.append("")
    lines.append(f"- [ ] Implemented in `{language}/`, idiomatically")
    lines.append("- [ ] Conformance vectors pass unmodified")
    lines.append(f"- [ ] `{gap['id']}` added to `{MANIFEST_PATHS[language]}`")
    lines.append("- [ ] `SPEC/features.yaml` updated in the same pull request")
    lines.append("- [ ] `python3 tools/parity_check.py` passes")
    lines.append(f"- [ ] `{TEST_COMMANDS[language]}` passes")
    lines.append("- [ ] No AI or tool attribution anywhere in the change")
    lines.append("")
    lines.append("Read `AGENTS.md` before starting. Section 4 covers porting.")

    return "\n".join(lines)


def gh(args: List[str], repo: Optional[str]) -> str:
    cmd = ["gh"] + args
    if repo:
        cmd += ["--repo", repo]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def existing_titles(repo: Optional[str]) -> Dict[str, int]:
    out = gh(
        [
            "issue",
            "list",
            "--label",
            LABEL,
            "--state",
            "all",
            "--limit",
            "500",
            "--json",
            "number,title",
        ],
        repo,
    )
    return {item["title"]: item["number"] for item in json.loads(out)}


def ensure_labels(repo: Optional[str], labels: List[str]) -> None:
    for label in labels:
        subprocess.run(
            ["gh", "label", "create", label, "--force"]
            + (["--repo", repo] if repo else []),
            capture_output=True,
            text=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync parity gap issues")
    parser.add_argument("--repo", help="owner/name; defaults to the current repo")
    parser.add_argument("--dry-run", action="store_true", help="print, do not create")
    parser.add_argument(
        "--include-backfill",
        action="store_true",
        help="also open issues for Stage 8 backfill entries",
    )
    args = parser.parse_args()

    registry = load_registry()
    gaps = collect_gaps(registry)
    grace = int(registry.get("grace_period_days", 14))
    bootstrap = registry.get("bootstrap") or {}
    today = date.today()

    # A gap in a language that has no source tree yet is a roadmap stage, not a
    # porting task. Opening an issue for it would produce noise nobody can act on.
    actionable = []
    for gap in gaps:
        if gap["language"] in bootstrap:
            continue
        if gap["backfill"] and not args.include_backfill:
            continue
        if not gap["reference"] and not gap["backfill"]:
            continue
        actionable.append(gap)

    if not actionable:
        print("No actionable parity gaps.")
        return 0

    by_id = {f["id"]: f for f in registry["features"]}
    existing = {} if args.dry_run else existing_titles(args.repo)

    if not args.dry_run:
        ensure_labels(
            args.repo,
            [LABEL]
            + [f"lang:{lang}" for lang in registry["languages"]]
            + ["level:0", "level:1", "level:2"],
        )

    created = 0
    for gap in actionable:
        title = title_for(gap)
        feature = by_id[gap["id"]]

        overdue_by = None
        if gap["backfill"]:
            milestone = parse_date(feature.get("milestone"))
            if milestone:
                overdue_by = (today - milestone).days
        else:
            since = [
                parse_date((feature["status"].get(lang) or {}).get("since"))
                for lang in gap["reference"]
            ]
            since = [d for d in since if d]
            if since:
                overdue_by = (today - min(since)).days - grace

        body = body_for(gap, overdue_by)
        labels = [LABEL, f"lang:{gap['language']}", f"level:{gap['level']}"]
        if overdue_by is not None and overdue_by > 0:
            labels.append("overdue")

        if title in existing:
            print(f"exists   #{existing[title]}  {title}")
            continue

        if args.dry_run:
            print(f"\n{'=' * 72}\nWOULD CREATE  {title}\nlabels: {labels}\n{'=' * 72}")
            print(body)
            created += 1
            continue

        out = gh(
            ["issue", "create", "--title", title, "--body", body]
            + sum((["--label", l] for l in labels), []),
            args.repo,
        )
        print(f"created  {out.strip()}  {title}")
        created += 1

    print(f"\n{created} issue(s) {'would be ' if args.dry_run else ''}created, "
          f"{len(actionable) - created} already open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
