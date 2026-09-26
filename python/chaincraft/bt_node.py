"""BitTorrent mesh client — Swarm on top of the Level 0 node.

Uses `Mesh.on_app` and `BitTorrentClient`. The wire node does not import this
module. Driven by conformance/runner/run_bittorrent.py.
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Any, Dict

from . import IMPL
from .bittorrent import BitTorrentClient
from .envelope import ProtocolError
from .mesh import MAX_STDIN_LINE, Mesh, emit


def main() -> int:
    out_lock = threading.Lock()
    mesh = Mesh(IMPL, on_event=lambda e: emit(e, out_lock))
    client = BitTorrentClient(mesh.broadcast)
    mesh.on_app = client.on_app
    mesh.start()
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
                cmd: Dict[str, Any] = json.loads(line)
                name = cmd.get("cmd")
                bt_event = client.handle_command(cmd)
                if bt_event is not None:
                    emit(bt_event, out_lock)
                elif name == "connect":
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
