"""Minimal TCP mesh node — SPEC/wire-v1.md §4, §5, §7, §8.

A process speaks the wire on one listening socket and a JSON-lines control
channel on stdin/stdout. The live interop runner drives three of these, one
per language. See conformance/runner/run_interop.py.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from typing import Any, Callable, Dict, List, Optional

from . import IMPL
from . import control
from .dedup import Deduplicator
from .envelope import Envelope, ProtocolError
from .framing import FrameReader, FramingError, encode_frame

EventFn = Callable[[Dict[str, Any]], None]


class _Peer:
    def __init__(self, sock: socket.socket, addr: str) -> None:
        self.sock = sock
        self.addr = addr
        self.lock = threading.Lock()
        self.impl: Optional[str] = None


class Mesh:
    """Listen, connect, hello, dedup and relay."""

    def __init__(self, impl: str = IMPL, on_event: Optional[EventFn] = None) -> None:
        self.impl = impl
        self.on_event = on_event or (lambda _e: None)
        self.dedup = Deduplicator()
        self.peers: List[_Peer] = []
        self.received: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.listen_addr = ""
        self._listener: Optional[socket.socket] = None

    def start(self, host: str = "127.0.0.1", port: int = 0) -> str:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(16)
        self._listener = listener
        bound_host, bound_port = listener.getsockname()
        self.listen_addr = f"{bound_host}:{bound_port}"
        threading.Thread(target=self._accept, daemon=True).start()
        return self.listen_addr

    def connect(self, addr: str) -> None:
        host, port_s = addr.rsplit(":", 1)
        sock = socket.create_connection((host, int(port_s)), timeout=5)
        sock.settimeout(None)
        self._add_peer(sock, addr)

    def broadcast(self, type_name: str, data: Any) -> str:
        env = Envelope.build(type_name, data)
        with self.lock:
            fresh = self.dedup.should_process(env)
            if fresh:
                self.received.append({"id": env.id, "type": env.type, "data": env.data})
            peers = list(self.peers)
        if fresh:
            for peer in peers:
                self._write(peer, env)
        return env.id

    def ids(self) -> List[str]:
        with self.lock:
            return [item["id"] for item in self.received]

    def close(self) -> None:
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        with self.lock:
            peers = list(self.peers)
        for peer in peers:
            try:
                peer.sock.close()
            except OSError:
                pass

    def _accept(self) -> None:
        assert self._listener is not None
        while True:
            try:
                sock, addr = self._listener.accept()
            except OSError:
                return
            self._add_peer(sock, f"{addr[0]}:{addr[1]}")

    def _add_peer(self, sock: socket.socket, addr: str) -> None:
        peer = _Peer(sock, addr)
        with self.lock:
            self.peers.append(peer)
        self._write(peer, control.hello(self.impl, listen=self.listen_addr))
        threading.Thread(target=self._read_loop, args=(peer,), daemon=True).start()

    def _write(self, peer: _Peer, env: Envelope) -> None:
        frame = encode_frame(env.to_bytes())
        with peer.lock:
            peer.sock.sendall(frame)

    def _read_loop(self, peer: _Peer) -> None:
        reader = FrameReader()
        try:
            while True:
                chunk = peer.sock.recv(65536)
                if not chunk:
                    break
                for body in reader.feed(chunk):
                    self._handle(peer, body)
        except (OSError, FramingError, ProtocolError, ValueError) as exc:
            self.on_event({"event": "error", "message": str(exc), "addr": peer.addr})
        finally:
            self._drop(peer)

    def _handle(self, peer: _Peer, body: bytes) -> None:
        env = Envelope.parse(body)
        if env.is_control():
            if env.type == control.HELLO:
                hello = control.parse_hello(env)
                peer.impl = hello["impl"]
                self.on_event(
                    {"event": "hello", "peer": hello["impl"], "addr": peer.addr}
                )
            return
        with self.lock:
            if not self.dedup.should_process(env):
                return
            self.received.append({"id": env.id, "type": env.type, "data": env.data})
            should_relay = self.dedup.should_relay(env)
            peers = list(self.peers)
        self.on_event(
            {"event": "received", "id": env.id, "type": env.type, "data": env.data}
        )
        if should_relay:
            for other in peers:
                if other is peer:
                    continue
                try:
                    self._write(other, env)
                except OSError:
                    pass

    def _drop(self, peer: _Peer) -> None:
        with self.lock:
            if peer in self.peers:
                self.peers.remove(peer)
        try:
            peer.sock.close()
        except OSError:
            pass


def _emit(event: Dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        sys.stdout.write(json.dumps(event, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def main() -> int:
    out_lock = threading.Lock()
    mesh = Mesh(IMPL, on_event=lambda e: _emit(e, out_lock))
    mesh.start()
    _emit({"event": "ready", "addr": mesh.listen_addr, "impl": IMPL}, out_lock)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            cmd = json.loads(line)
            name = cmd.get("cmd")
            if name == "connect":
                mesh.connect(cmd["addr"])
                _emit({"event": "connected", "addr": cmd["addr"]}, out_lock)
            elif name == "send":
                digest = mesh.broadcast(cmd["type"], cmd["data"])
                _emit({"event": "sent", "id": digest}, out_lock)
            elif name == "ids":
                _emit({"event": "ids", "ids": mesh.ids()}, out_lock)
            elif name == "quit":
                break
            else:
                _emit({"event": "error", "message": f"unknown cmd {name}"}, out_lock)
    finally:
        mesh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
