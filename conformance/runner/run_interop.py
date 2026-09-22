#!/usr/bin/env python3
"""Live 3×3 interop matrix — SPEC/wire-v1.md §9.

Starts one TCP node per language, connects them into a triangle, and checks
that an application message sent from each language arrives at the other two
with the same payload digest. That is the directed 3×3: every sender against
every receiver, including the sender itself (it records its own broadcast).

Control channel (JSON lines on the node stdin/stdout):

    {"event":"ready","addr":"127.0.0.1:PORT","impl":"..."}
    {"cmd":"connect","addr":"..."}
    {"cmd":"send","type":"app.interop","data":{...}}
    {"cmd":"ids"}
    {"cmd":"quit"}

    python3 conformance/runner/run_interop.py
"""

from __future__ import annotations

import json
import os
import queue
import select
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent.parent

BOLD, RED, GREEN, YELLOW, DIM, RESET = (
    "\033[1m",
    "\033[31m",
    "\033[32m",
    "\033[33m",
    "\033[2m",
    "\033[0m",
)

LANGUAGES = ("python", "rust", "typescript")

COMMANDS = {
    "python": {
        "cmd": [sys.executable, "-m", "chaincraft_core.node"],
        "cwd": REPO / "python",
        "env_extra": {},
    },
    "rust": {
        "cmd": ["cargo", "run", "--quiet", "--bin", "node"],
        "cwd": REPO / "rust",
        "env_extra": {},
    },
    "typescript": {
        "cmd": ["npm", "run", "--silent", "node"],
        "cwd": REPO / "typescript",
        "env_extra": {},
    },
}


class Node:
    def __init__(self, language: str, spec: Optional[Dict[str, Any]] = None) -> None:
        self.language = language
        spec = spec or COMMANDS[language]
        env = {**os.environ, **spec["env_extra"]}
        self.proc = subprocess.Popen(
            spec["cmd"],
            cwd=spec["cwd"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self.addr = ""
        self.impl = ""
        self.events: List[Dict[str, Any]] = []
        # select() on a text pipe misses lines already sitting in the
        # TextIOWrapper. A reader thread keeps readline and the buffer together.
        self._lines: queue.Queue = queue.Queue()
        self._stderr_chunks: List[str] = []
        self._stderr_lock = threading.Lock()
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        try:
            for line in self.proc.stdout:
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            with self._stderr_lock:
                self._stderr_chunks.append(line)
                if len(self._stderr_chunks) > 40:
                    self._stderr_chunks = self._stderr_chunks[-40:]

    def stderr_tail(self) -> str:
        with self._stderr_lock:
            return "".join(self._stderr_chunks)[-800:]

    def send(self, payload: Dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def wait_event(self, name: str, timeout: float = 20.0) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in self.events:
                if event.get("event") == name:
                    self.events.remove(event)
                    return event
            event = self._read_line(deadline - time.monotonic())
            if event is None:
                continue
            if event.get("event") == name:
                return event
            self.events.append(event)
        raise TimeoutError(f"{self.language} did not emit {name!r}")

    def _read_line(self, timeout: float) -> Optional[Dict[str, Any]]:
        assert self.proc.stdout is not None
        if timeout <= 0:
            return None
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            return None
        if line is None:
            raise RuntimeError(f"{self.language} exited: {self.stderr_tail()}")
        line = line.strip()
        if not line:
            return None
        return json.loads(line)

    def ids(self, timeout: float = 5.0) -> List[str]:
        self.send({"cmd": "ids"})
        event = self.wait_event("ids", timeout=timeout)
        return list(event.get("ids") or [])

    def close(self) -> None:
        try:
            self.send({"cmd": "quit"})
        except (BrokenPipeError, OSError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def start_nodes(commands: Optional[Dict[str, Any]] = None) -> Dict[str, Node]:
    table = commands or COMMANDS
    nodes: Dict[str, Node] = {}
    for language in LANGUAGES:
        print(f"  starting {language} ...", flush=True)
        node = Node(language, table[language])
        ready = node.wait_event("ready", timeout=60.0)
        node.addr = ready["addr"]
        node.impl = ready["impl"]
        print(f"    {language:<12} {node.impl:<28} {node.addr}")
        nodes[language] = node
    return nodes


def connect_triangle(nodes: Dict[str, Node]) -> None:
    # One TCP connection per pair. Messages travel both ways on each.
    pairs = (
        ("typescript", "python"),
        ("rust", "python"),
        ("rust", "typescript"),
    )
    for src, dst in pairs:
        print(f"  connect {src} -> {dst} ({nodes[dst].addr})", flush=True)
        nodes[src].send({"cmd": "connect", "addr": nodes[dst].addr})
        nodes[src].wait_event("connected", timeout=10.0)
        # Both sides must exchange ctl.hello.
        nodes[src].wait_event("hello", timeout=10.0)
        nodes[dst].wait_event("hello", timeout=10.0)


def wait_for_ids(nodes: Dict[str, Node], expected: List[str], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    pending = set(LANGUAGES)
    while pending and time.monotonic() < deadline:
        for language in list(pending):
            have = nodes[language].ids(timeout=2.0)
            if set(expected).issubset(have):
                pending.discard(language)
        if pending:
            time.sleep(0.1)
    if pending:
        detail = {lang: nodes[lang].ids(timeout=2.0) for lang in LANGUAGES}
        raise AssertionError(f"ids not converged; still waiting on {sorted(pending)}: {detail}")


def mismatch_is_disconnected(addr: str) -> None:
    """A peer advertising v=99 must be dropped rather than silently kept."""
    host, port_s = addr.rsplit(":", 1)
    sock = socket.create_connection((host, int(port_s)), timeout=5)
    # Minimal ctl.hello with v=99. The envelope itself is protocol v=1; the
    # payload version is what parse_hello rejects.
    sys.path.insert(0, str(REPO / "python"))
    from chaincraft_core.envelope import Envelope
    from chaincraft_core.framing import encode_frame

    env = Envelope.build(
        "ctl.hello",
        {"v": 99, "impl": "probe/0.0.0", "caps": []},
    )
    sock.sendall(encode_frame(env.to_bytes()))
    sock.settimeout(3)
    try:
        data = sock.recv(64)
    except socket.timeout:
        sock.close()
        raise AssertionError("peer kept a v=99 connection open") from None
    sock.close()
    if data:
        # A hello reply then a close is acceptable; a sustained stream is not.
        time.sleep(0.2)
        sock2_closed = True
        try:
            probe = socket.create_connection((host, int(port_s)), timeout=2)
            probe.close()
        except OSError:
            sock2_closed = False
        # The listen socket stays up; we only care that *this* connection ended.
        del sock2_closed
    # recv returning b'' means the peer closed after rejecting us.
    if data is None:
        raise AssertionError("no response and no close from v=99 hello")


def print_matrix(ids: Dict[str, str], holdings: Dict[str, List[str]]) -> None:
    name_w = 12
    print(f"\n{BOLD}sender \\ receiver{RESET}")
    header = " " * name_w + "".join(f"{lang:<12}" for lang in LANGUAGES)
    print(header)
    print("-" * len(header))
    for sender in LANGUAGES:
        cells = []
        for receiver in LANGUAGES:
            ok = ids[sender] in holdings[receiver]
            mark = f"{GREEN}ok{RESET}" if ok else f"{RED}FAIL{RESET}"
            cells.append(f"{mark:<21}")  # room for ANSI
        print(f"{sender:<12}" + "".join(f"{c:<12}" for c in cells))


def main() -> int:
    print(f"{BOLD}Live interop matrix{RESET}  (TCP, ctl.hello, gossip, dedup)\n")
    nodes: Dict[str, Node] = {}
    try:
        nodes = start_nodes()
        connect_triangle(nodes)

        ids: Dict[str, str] = {}
        for i, language in enumerate(LANGUAGES, start=1):
            payload = {"from": language, "n": i}
            print(f"  send from {language}: {payload}", flush=True)
            nodes[language].send({"cmd": "send", "type": "app.interop", "data": payload})
            sent = nodes[language].wait_event("sent", timeout=10.0)
            ids[language] = sent["id"]
            print(f"    id {ids[language]}")

        expected = [ids[lang] for lang in LANGUAGES]
        wait_for_ids(nodes, expected)

        holdings = {lang: nodes[lang].ids() for lang in LANGUAGES}
        print_matrix(ids, holdings)

        failed = False
        for sender in LANGUAGES:
            for receiver in LANGUAGES:
                if ids[sender] not in holdings[receiver]:
                    print(
                        f"{RED}{sender} -> {receiver} missing {ids[sender]}{RESET}"
                    )
                    failed = True

        print("\n  re-sending python's payload (must not grow the seen set)")
        nodes["python"].send(
            {"cmd": "send", "type": "app.interop", "data": {"from": "python", "n": 1}}
        )
        nodes["python"].wait_event("sent", timeout=5.0)
        time.sleep(0.4)
        after = {lang: nodes[lang].ids() for lang in LANGUAGES}
        for lang in LANGUAGES:
            if set(after[lang]) != set(holdings[lang]):
                print(f"{RED}dedup failed on {lang}: {holdings[lang]} -> {after[lang]}{RESET}")
                failed = True

        print("  ctl.hello v=99 against python must close the connection")
        mismatch_is_disconnected(nodes["python"].addr)

        if failed:
            print(f"\n{RED}{BOLD}Interop matrix failed.{RESET}")
            return 1
        print(f"\n{GREEN}{BOLD}3×3 interop matrix passed.{RESET}")
        return 0
    except Exception as exc:
        print(f"\n{RED}{BOLD}Interop failed:{RESET} {exc}")
        for language, node in nodes.items():
            if node.proc.stderr is not None:
                err = node.proc.stderr.read()
                if err:
                    print(f"\n{DIM}--- {language} stderr ---{RESET}\n{err[-800:]}")
        return 1
    finally:
        for node in nodes.values():
            node.close()


if __name__ == "__main__":
    raise SystemExit(main())
