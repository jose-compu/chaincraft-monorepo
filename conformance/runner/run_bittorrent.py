#!/usr/bin/env python3
"""Live mixed-language BitTorrent swarm — SPEC/features/bittorrent-swarm.md.

Starts one node per language, connects them as a triangle, and rotates the
seeder: Python, then Rust, then TypeScript. The other two leech. Every client
must assemble the same hex payload.

    python3 conformance/runner/run_bittorrent.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "conformance" / "runner"))

from run_interop import (  # noqa: E402
    BOLD,
    GREEN,
    LANGUAGES,
    RED,
    RESET,
    connect_triangle,
    start_nodes,
)

BT_COMMANDS = {
    "python": {
        "cmd": [sys.executable, "-m", "chaincraft.bt_node"],
        "cwd": REPO / "python",
        "env_extra": {},
    },
    "rust": {
        "cmd": ["cargo", "run", "--quiet", "--bin", "chaincraft-bt-node"],
        "cwd": REPO / "rust",
        "env_extra": {},
    },
    "typescript": {
        "cmd": ["npm", "run", "--silent", "bt-node"],
        "cwd": REPO / "typescript",
        "env_extra": {},
    },
}

EXPECTED = {
    "python": ("demo-python", "ABCDEFGHIJKL", "4142434445464748494a4b4c"),
    "rust": ("demo-rust", "MNOPQRSTUVWX", "4d4e4f505152535455565758"),
    "typescript": ("demo-typescript", "abcdefghijkl", "6162636465666768696a6b6c"),
}
PIECE_SIZE = 4


def status(node) -> List[dict]:
    node.send({"cmd": "bt.status"})
    event = node.wait_event("bt.status", timeout=10.0)
    return list(event.get("torrents") or [])


def wait_torrent(nodes: Dict, digest: str, languages, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    pending = set(languages)
    while pending and time.monotonic() < deadline:
        for language in list(pending):
            torrents = status(nodes[language])
            if any(item.get("info_hash") == digest for item in torrents):
                pending.discard(language)
        if pending:
            time.sleep(0.1)
    if pending:
        raise AssertionError(f"metainfo not seen by {sorted(pending)} for {digest}")


def wait_assembled(nodes: Dict, digest: str, hex_payload: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    pending = set(LANGUAGES)
    while pending and time.monotonic() < deadline:
        for language in list(pending):
            torrents = status(nodes[language])
            match = next((item for item in torrents if item.get("info_hash") == digest), None)
            if match and match.get("assembled") == hex_payload:
                pending.discard(language)
        if pending:
            time.sleep(0.1)
    if pending:
        detail = {lang: status(nodes[lang]) for lang in LANGUAGES}
        raise AssertionError(f"swarm not complete on {sorted(pending)}: {detail}")


def main() -> int:
    print(f"{BOLD}Mixed BitTorrent swarm{RESET}  (Python / Rust / TypeScript)\n")
    nodes = {}
    try:
        nodes = start_nodes(BT_COMMANDS)
        connect_triangle(nodes)
        for seeder in LANGUAGES:
            name, payload, hex_payload = EXPECTED[seeder]
            print(f"  seed from {seeder}: {payload!r} piece_size={PIECE_SIZE}", flush=True)
            nodes[seeder].send(
                {
                    "cmd": "bt.seed",
                    "peer": seeder,
                    "name": name,
                    "data": payload,
                    "piece_size": PIECE_SIZE,
                }
            )
            seeded = nodes[seeder].wait_event("bt.seeded", timeout=10.0)
            digest = seeded["info_hash"]
            print(f"    info_hash {digest}", flush=True)
            leechers = [lang for lang in LANGUAGES if lang != seeder]
            wait_torrent(nodes, digest, leechers)
            for leecher in leechers:
                nodes[leecher].send({"cmd": "bt.leech", "peer": leecher, "info_hash": digest})
                nodes[leecher].wait_event("bt.leech", timeout=10.0)
                print(f"    leech {leecher}", flush=True)
            wait_assembled(nodes, digest, hex_payload)
            print(f"    {GREEN}all three assembled {hex_payload}{RESET}", flush=True)
        print(f"\n{GREEN}{BOLD}3-client BitTorrent swarm passed.{RESET}", flush=True)
        return 0
    except Exception as exc:
        print(f"\n{RED}{BOLD}BitTorrent swarm failed:{RESET} {exc}", flush=True)
        for language, node in nodes.items():
            err = node.stderr_tail()
            if err:
                print(f"\n--- {language} stderr ---\n{err}", flush=True)
        return 1
    finally:
        for node in nodes.values():
            node.close()


if __name__ == "__main__":
    raise SystemExit(main())
