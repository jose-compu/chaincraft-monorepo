"""Minimal TCP mesh node — SPEC/wire-v1.md §4, §5, §7, §8.

Wire commands only: connect / send / ids / quit. Application protocols attach
to `Mesh.on_app` in their own entrypoints.
"""

from __future__ import annotations

import json
import sys
import threading

from . import IMPL
from .envelope import ProtocolError
from .mesh import MAX_STDIN_LINE, Mesh, emit, parse_listen


def main() -> int:
    out_lock = threading.Lock()
    mesh = Mesh(IMPL, on_event=lambda e: emit(e, out_lock))
    host, port = parse_listen(sys.argv[1] if len(sys.argv) > 1 else None)
    mesh.start(host, port)
    emit({"event": "ready", "addr": mesh.listen_addr, "impl": IMPL}, out_lock)
    try:
        for line in sys.stdin:
            if len(line) > MAX_STDIN_LINE:
                emit({"event": "error", "message": "line too long"}, out_lock)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
                name = cmd.get("cmd")
                if name == "connect":
                    mesh.connect(cmd["addr"])
                    emit({"event": "connected", "addr": cmd["addr"]}, out_lock)
                elif name == "send":
                    digest = mesh.broadcast(cmd["type"], cmd["data"])
                    emit({"event": "sent", "id": digest}, out_lock)
                elif name == "ids":
                    emit({"event": "ids", "ids": mesh.ids()}, out_lock)
                elif name == "quit":
                    break
                else:
                    emit({"event": "error", "message": f"unknown cmd {name}"}, out_lock)
            except (ValueError, OSError, ProtocolError, TypeError, KeyError, json.JSONDecodeError) as exc:
                emit({"event": "error", "message": str(exc)}, out_lock)
    finally:
        mesh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
