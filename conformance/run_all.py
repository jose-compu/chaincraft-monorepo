#!/usr/bin/env python3
"""Run the shared conformance vectors against every implementation present.

Implementations that do not exist yet are reported as pending rather than
failing, so this is useful throughout the staged rollout.

    python3 conformance/run_all.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
VECTORS = REPO / "conformance" / "vectors"

BOLD, RED, YELLOW, GREEN, DIM, RESET = (
    "\033[1m",
    "\033[31m",
    "\033[33m",
    "\033[32m",
    "\033[2m",
    "\033[0m",
)

SUITES = {
    "python": {
        "marker": "python/pyproject.toml",
        "cwd": "python",
        "cmd": [sys.executable, "-m", "pytest", "tests/test_vectors.py", "-v"],
        "stage": 2,
    },
    "rust": {
        "marker": "rust/Cargo.toml",
        "cwd": "rust",
        "cmd": ["cargo", "test", "--test", "conformance", "--", "--nocapture"],
        "stage": 5,
    },
    "typescript": {
        "marker": "typescript/package.json",
        "cwd": "typescript",
        "cmd": ["npm", "test"],
        "stage": 4,
    },
}


def count_cases(data: Dict) -> int:
    """Count every case in every section.

    Sections are the lists of objects; a list of plain values is metadata, such
    as pipeline.json's registry order. Replay cases nest their own steps.
    """
    total = 0
    for value in data.values():
        if not isinstance(value, list) or not value:
            continue
        if not all(isinstance(item, dict) for item in value):
            continue
        total += sum(len(case.get("steps", [1])) for case in value)
    return total


def vector_inventory() -> List[Tuple[str, str, int]]:
    rows = []
    for path in sorted(VECTORS.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        rows.append((path.name, data.get("feature", "?"), count_cases(data)))
    return rows


def run(language: str, spec: Dict) -> Optional[bool]:
    """Returns True on pass, False on fail, None when not implemented yet."""
    if not (REPO / spec["marker"]).exists():
        return None
    print(f"\n{BOLD}{'=' * 72}\n{language}\n{'=' * 72}{RESET}")
    # Subprocesses write straight to fd 1; flush so our output stays in order
    # when this script is piped.
    sys.stdout.flush()
    result = subprocess.run(spec["cmd"], cwd=REPO / spec["cwd"])
    return result.returncode == 0


def main() -> int:
    if not VECTORS.exists() or not any(VECTORS.glob("*.json")):
        print(f"{RED}No vectors found.{RESET} Run conformance/generate_vectors.py first.")
        return 1

    print(f"{BOLD}Conformance vectors{RESET}\n")
    total = 0
    for name, feature, count in vector_inventory():
        print(f"  {name:<26} {feature:<26} {count:>4} cases")
        total += count
    print(f"\n  {BOLD}{total} cases total{RESET}")

    results: Dict[str, Optional[bool]] = {}
    for language, spec in SUITES.items():
        results[language] = run(language, spec)

    print(f"\n{BOLD}{'=' * 72}\nSummary\n{'=' * 72}{RESET}")
    failed = False
    for language, outcome in results.items():
        if outcome is None:
            stage = SUITES[language]["stage"]
            print(f"  {language:<12} {DIM}pending — Stage {stage} not started{RESET}")
        elif outcome:
            print(f"  {language:<12} {GREEN}pass{RESET}")
        else:
            print(f"  {language:<12} {RED}FAIL{RESET}")
            failed = True

    if failed:
        print(
            f"\n{RED}{BOLD}Conformance failed.{RESET} A failure here is a wire "
            f"protocol violation.\nNever edit a vector to make it pass — see "
            f"AGENTS.md section 7."
        )
        return 1

    pending = [lang for lang, outcome in results.items() if outcome is None]
    if pending:
        print(f"\n{YELLOW}Passing, with {', '.join(pending)} not yet implemented.{RESET}")
    else:
        print(f"\n{GREEN}{BOLD}All implementations conformant.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
