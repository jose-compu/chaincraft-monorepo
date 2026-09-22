#!/usr/bin/env python3
"""Parity gate — enforces SPEC/features.yaml against the implementations.

Runs on every pull request and is never skipped by path filters. See AGENTS.md
section 5 for the rules it enforces.

    python3 tools/parity_check.py             # full check, exit 1 on failure
    python3 tools/parity_check.py --summary   # parity table
    python3 tools/parity_check.py --gaps      # open gaps, human readable
    python3 tools/parity_check.py --gaps --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import yaml
except ImportError:
    sys.stderr.write("parity_check requires PyYAML: pip install pyyaml\n")
    raise SystemExit(2)

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "SPEC" / "features.yaml"
RELEASE = REPO / "SPEC" / "release.yaml"

VALID_STATES = {"implemented", "in-progress", "planned", "exempt"}
SATISFIED = {"implemented", "exempt"}

# How each implementation reports the feature IDs it claims, and the marker file
# proving the implementation exists at all.
MANIFESTS = {
    "python": {
        "cwd": "python",
        "marker": "python/chaincraft_core/__init__.py",
        "cmd": [sys.executable, "-m", "chaincraft_core.features"],
    },
    "rust": {
        "cwd": "rust",
        "marker": "rust/Cargo.toml",
        "cmd": ["cargo", "run", "--quiet", "--bin", "features"],
    },
    "typescript": {
        "cwd": "typescript",
        "marker": "typescript/package.json",
        "cmd": ["npm", "run", "--silent", "features"],
    },
}

BOLD, RED, YELLOW, GREEN, DIM, RESET = (
    "\033[1m",
    "\033[31m",
    "\033[33m",
    "\033[32m",
    "\033[2m",
    "\033[0m",
)


class Report:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, feature: str, message: str) -> None:
        self.errors.append(f"{feature}: {message}")

    def warn(self, feature: str, message: str) -> None:
        self.warnings.append(f"{feature}: {message}")


def load_registry() -> Dict[str, Any]:
    with REGISTRY.open() as handle:
        return yaml.safe_load(handle)


def read_manifest(language: str) -> Optional[Set[str]]:
    """Ask an implementation which features it provides.

    Returns None when the implementation is not present in the tree, which is
    distinct from an implementation reporting an empty feature set.
    """
    spec = MANIFESTS[language]
    if not (REPO / spec["marker"]).exists():
        return None
    try:
        result = subprocess.run(
            spec["cmd"],
            cwd=REPO / spec["cwd"],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"could not run {language} manifest: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"{language} manifest exited {result.returncode}:\n{result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{language} manifest emitted invalid JSON: {exc}") from exc
    return set(payload.get("features", []))


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def _quoted(text: str, name: str) -> Optional[str]:
    match = re.search(
        rf"(?:^|\s){re.escape(name)}\s*(?::[^=]+)?=\s*[\"']([^\"']+)[\"']",
        text,
        re.M,
    )
    return match.group(1) if match else None


def _integer(text: str, name: str) -> Optional[int]:
    match = re.search(rf"{name}[^\n=]*=\s*(\d+)", text)
    return int(match.group(1)) if match else None


def check_spec_release(report: Report) -> None:
    """The spec release, the package versions, and the document stamps agree."""
    if not RELEASE.exists():
        report.error("<spec>", "SPEC/release.yaml is missing")
        return
    with RELEASE.open() as handle:
        release_doc = yaml.safe_load(handle)
    release = str(release_doc.get("release") or "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", release):
        report.error("<spec>", f"spec release {release!r} is not major.minor.patch")
        return
    if release_doc.get("status") != "current":
        report.error("<spec>", "SPEC/release.yaml status must be current")
    if parse_date(release_doc.get("since")) is None:
        report.error("<spec>", "SPEC/release.yaml since must be YYYY-MM-DD")

    packages = {
        "python": _quoted((REPO / "python/pyproject.toml").read_text(), "version"),
        "rust": _quoted((REPO / "rust/Cargo.toml").read_text(), "version"),
        "typescript": json.loads((REPO / "typescript/package.json").read_text())["version"],
    }
    constants = {
        "python": _quoted((REPO / "python/chaincraft_core/__init__.py").read_text(), "__version__"),
        "rust": _quoted((REPO / "rust/src/features.rs").read_text(), "VERSION"),
        "typescript": _quoted((REPO / "typescript/src/features.ts").read_text(), "VERSION"),
    }
    for language, found in packages.items():
        if found != release:
            report.error("<spec>", f"{language} package is {found}, spec release is {release}")
    for language, found in constants.items():
        if found != release:
            report.error("<spec>", f"{language} version constant is {found}, spec release is {release}")

    wire = release_doc.get("wire_protocol")
    wire_constants = {
        "python": _integer((REPO / "python/chaincraft_core/envelope.py").read_text(), "PROTOCOL_VERSION"),
        "rust": _integer((REPO / "rust/src/features.rs").read_text(), "WIRE_VERSION"),
        "typescript": _integer((REPO / "typescript/src/features.ts").read_text(), "WIRE_VERSION"),
    }
    for language, found in wire_constants.items():
        if found != wire:
            report.error("<spec>", f"{language} wire version is {found}, release.yaml says {wire}")

    listed = release_doc.get("documents") or []
    found_docs = sorted(str(path.relative_to(REPO)) for path in (REPO / "SPEC").rglob("*.md"))
    if listed != found_docs:
        missing = sorted(set(found_docs) - set(listed))
        extra = sorted(set(listed) - set(found_docs))
        if missing:
            report.error("<spec>", f"spec files missing from SPEC/release.yaml: {missing}")
        if extra:
            report.error("<spec>", f"SPEC/release.yaml lists missing files: {extra}")
    stamp = f"**Release:** {release}"
    for path in listed:
        file = REPO / path
        if file.exists() and stamp not in file.read_text():
            report.error("<spec>", f"{path} does not carry {stamp}")


def check(registry: Dict[str, Any], today: date) -> Report:
    report = Report()
    check_spec_release(report)
    languages: List[str] = registry["languages"]
    grace = int(registry.get("grace_period_days", 14))
    bootstrap = registry.get("bootstrap") or {}

    manifests: Dict[str, Optional[Set[str]]] = {}
    for language in languages:
        try:
            manifests[language] = read_manifest(language)
        except RuntimeError as exc:
            report.error("<manifest>", str(exc))
            manifests[language] = None

    seen_ids: Set[str] = set()

    for feature in registry["features"]:
        fid = feature["id"]
        if fid in seen_ids:
            report.error(fid, "duplicate feature id in registry")
        seen_ids.add(fid)

        status = feature.get("status") or {}
        is_backfill = bool(feature.get("backfill"))
        any_implemented = any(
            (status.get(language) or {}).get("state") == "implemented"
            for language in languages
        )

        # Vectors are written with the first implementation (AGENTS.md rule 4),
        # so they are required once a feature exists somewhere, not before.
        vectors = feature.get("vectors")
        if vectors and any_implemented and not (REPO / vectors).exists():
            report.error(fid, f"declared vectors not found: {vectors}")

        missing_langs = set(languages) - set(status)
        if missing_langs:
            report.error(fid, f"registry missing languages: {sorted(missing_langs)}")

        implemented_dates: List[date] = []

        for language in languages:
            entry = status.get(language)
            if entry is None:
                continue
            state = entry.get("state")

            if state not in VALID_STATES:
                report.error(fid, f"{language}: invalid state {state!r}")
                continue

            if state == "exempt":
                if not entry.get("reason"):
                    report.error(fid, f"{language}: exempt requires a reason")
                elif not entry.get("reviewed_by"):
                    report.warn(fid, f"{language}: exemption awaiting human review")
                continue

            if state == "in-progress" and not entry.get("issue"):
                report.error(fid, f"{language}: in-progress requires a tracking issue")

            if state == "implemented":
                when = parse_date(entry.get("since"))
                if when is None:
                    report.error(fid, f"{language}: implemented requires a valid since")
                else:
                    implemented_dates.append(when)

            # Registry and implementation must agree, in both directions.
            claimed = manifests.get(language)
            if claimed is not None:
                if state == "implemented" and fid not in claimed:
                    report.error(
                        fid,
                        f"{language}: registry says implemented but the manifest "
                        f"does not report it",
                    )
                elif state != "implemented" and fid in claimed:
                    report.error(
                        fid,
                        f"{language}: manifest reports it but the registry says "
                        f"{state}",
                    )

        # Deadline enforcement, only once a feature exists somewhere.
        if not implemented_dates:
            continue

        gaps = [
            language
            for language in languages
            if (status.get(language) or {}).get("state") not in SATISFIED
        ]
        if not gaps:
            continue

        if is_backfill:
            milestone = parse_date(feature.get("milestone"))
            if milestone is None:
                report.error(fid, "backfill entry requires a milestone date")
            elif today > milestone:
                report.error(
                    fid,
                    f"backfill milestone {milestone} passed; still missing in "
                    f"{sorted(gaps)}",
                )
            continue

        age = (today - min(implemented_dates)).days
        overdue = [g for g in gaps if g not in bootstrap]
        blocked = [g for g in gaps if g in bootstrap]

        if blocked:
            report.warn(
                fid,
                f"not yet ported to {sorted(blocked)} (bootstrap: implementation "
                f"does not exist yet)",
            )
        if overdue and age > grace:
            report.error(
                fid,
                f"implemented {age} days ago, past the {grace}-day grace period, "
                f"still missing in {sorted(overdue)}",
            )
        elif overdue:
            report.warn(
                fid,
                f"missing in {sorted(overdue)}, {grace - age} days left in the "
                f"grace period",
            )

    # A manifest reporting an ID the registry has never heard of.
    for language, claimed in manifests.items():
        if claimed is None:
            continue
        for fid in sorted(claimed - seen_ids):
            report.error(fid, f"{language}: reported by manifest but absent from registry")

    return report


def collect_gaps(registry: Dict[str, Any]) -> List[Dict[str, Any]]:
    gaps = []
    for feature in registry["features"]:
        status = feature.get("status") or {}
        for language in registry["languages"]:
            entry = status.get(language) or {}
            if entry.get("state") in SATISFIED:
                continue
            gaps.append(
                {
                    "id": feature["id"],
                    "language": language,
                    "state": entry.get("state", "missing"),
                    "level": feature.get("level"),
                    "spec": feature.get("spec"),
                    "vectors": feature.get("vectors"),
                    "summary": feature.get("summary", ""),
                    "backfill": bool(feature.get("backfill")),
                    "milestone": str(feature.get("milestone") or ""),
                    "legacy": feature.get("legacy") or "",
                    "issue": entry.get("issue"),
                    "reference": sorted(
                        lang
                        for lang in registry["languages"]
                        if (status.get(lang) or {}).get("state") == "implemented"
                    ),
                }
            )
    return gaps


def _cell(text: str, colour: str, width: int) -> str:
    """Pad to ``width`` based on visible length, then colour it."""
    return colour + text + RESET + " " * max(0, width - len(text))


def print_summary(registry: Dict[str, Any]) -> None:
    languages = registry["languages"]
    marks = {
        "implemented": ("yes", GREEN),
        "in-progress": ("wip", YELLOW),
        "planned": ("no", RED),
        "exempt": ("n/a", DIM),
    }
    name_w = max(len(f["id"]) for f in registry["features"]) + 2
    col_w = 13
    rule = "-" * (name_w + 5 + col_w * len(languages))

    print(f"\n{BOLD}Parity registry{RESET}  ({REGISTRY.relative_to(REPO)})\n")
    print(
        BOLD
        + "feature".ljust(name_w)
        + "lvl  "
        + "".join(language.ljust(col_w) for language in languages)
        + RESET
    )
    print(rule)

    totals = {language: 0 for language in languages}
    for feature in registry["features"]:
        status = feature.get("status") or {}
        row = feature["id"].ljust(name_w) + f"{feature.get('level', '?')}    "
        for language in languages:
            state = (status.get(language) or {}).get("state", "planned")
            if state in SATISFIED:
                totals[language] += 1
            text, colour = marks.get(state, (state, ""))
            row += _cell(text, colour, col_w)
        print(row.rstrip())

    count = len(registry["features"])
    print(rule)
    footer = "parity".ljust(name_w) + "     "
    for language in languages:
        pct = 100 * totals[language] // count if count else 0
        colour = GREEN if pct == 100 else YELLOW if pct >= 50 else RED
        footer += _cell(f"{totals[language]}/{count} {pct}%", colour, col_w)
    print(BOLD + footer.rstrip() + RESET + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Chaincraft parity gate")
    parser.add_argument("--summary", action="store_true", help="print the parity table")
    parser.add_argument("--gaps", action="store_true", help="list open parity gaps")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--today", help="override today's date, YYYY-MM-DD")
    args = parser.parse_args()

    registry = load_registry()

    if args.summary:
        print_summary(registry)
        return 0

    if args.gaps:
        gaps = collect_gaps(registry)
        if args.json:
            json.dump(gaps, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            if not gaps:
                print(f"{GREEN}No parity gaps.{RESET}")
            for gap in gaps:
                tag = " [backfill]" if gap["backfill"] else ""
                print(f"{RED}{gap['id']}{RESET} -> {gap['language']} ({gap['state']}){tag}")
                print(f"    {gap['summary']}")
                print(f"    spec: {gap['spec']}")
        return 0

    today = parse_date(args.today) or date.today()
    report = check(registry, today)

    for warning in report.warnings:
        print(f"{YELLOW}warn{RESET}  {warning}")
    for error in report.errors:
        print(f"{RED}fail{RESET}  {error}")

    if report.errors:
        print(
            f"\n{RED}{BOLD}Parity gate failed{RESET} — "
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
        )
        return 1

    print(
        f"\n{GREEN}{BOLD}Parity gate passed{RESET} — "
        f"{len(report.warnings)} warning(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
