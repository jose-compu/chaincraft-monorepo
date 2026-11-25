"""TCP mesh — SPEC/wire-v1.md §4, §5, §7, §8.

Application protocols attach via `on_app`, not by editing this module.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from typing import Any, Callable, Dict, List, Optional

from . import IMPL
from . import control
from .adapters import UdpLink
from .channel import parse_address
from .dedup import Deduplicator
from .discovery import is_connect_allowed, is_resolved_ip_allowed
from .envelope import Envelope, ProtocolError
from .framing import MAX_UDP_BYTES, FrameReader, FramingError, encode_frame
from .hybrid import hello_caps

MAX_PEERS = 256
MAX_RECEIVED = 4096
MAX_STDIN_LINE = 1_048_576
CONNECT_TIMEOUT_S = 5
NODE_MAX_FRAME = 262_144
DEFAULT_LISTEN = "0.0.0.0:9735"


def parse_listen(raw: Optional[str] = None) -> tuple[str, int]:
    """Parse ``host:port``. Default is all interfaces on 9735."""
    text = DEFAULT_LISTEN if raw is None or raw == "" else raw
    if ":" not in text:
        raise ValueError("listen must be host:port")
    host, port_s = text.rsplit(":", 1)
    port = int(port_s)
    if not host or port < 0 or port > 65535:
        raise ValueError("invalid listen")
    return host, port


EventFn = Callable[[Dict[str, Any]], None]
AppFn = Callable[[str, Any], None]
LinkFn = Callable[[str, str, Any], None]


class _Peer:
    def __init__(self, sock: socket.socket, addr: str) -> None:
        self.sock = sock
        self.addr = addr
        self.lock = threading.Lock()
        self.impl: Optional[str] = None


class Mesh:
    """Listen, connect, hello, dedup and relay."""

    def __init__(
        self,
        impl: str = IMPL,
        on_event: Optional[EventFn] = None,
        on_app: Optional[AppFn] = None,
        on_link: Optional[LinkFn] = None,
        allow_peer: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.impl = impl
        self.on_event = on_event or (lambda _e: None)
        self.on_app = on_app or (lambda _t, _d: None)
        self.on_link = on_link or (lambda _addr, _t, _d: None)
        self.allow_peer = allow_peer or (lambda _a: True)
        self.dedup = Deduplicator()
        self.peers: List[_Peer] = []
        self.received: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.listen_addr = ""
        self._listener: Optional[socket.socket] = None
        self._udp: Optional[UdpLink] = None
        self._udp_peers: List[str] = []

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

    def bind_udp(self) -> str:
        """Optional datagram listener. Advertised as the ``udp`` hello cap."""
        if self._udp is None:
            self._udp = UdpLink()
            threading.Thread(target=self._udp_loop, daemon=True).start()
        return self._udp.host_port

    def connect(self, addr: str) -> None:
        parsed = parse_address(addr)
        if parsed["ok"] and parsed["scheme"] == "udp":
            self._connect_udp(parsed["canonical"].split("://", 1)[1])
            return
        if parsed["ok"] and parsed["scheme"] == "tcp":
            addr = parsed["canonical"].split("://", 1)[1]
        elif not parsed["ok"]:
            raise ValueError("address not allowed")
        else:
            raise ValueError("address not allowed")
        if not is_connect_allowed(addr):
            raise ValueError("address not allowed")
        host, port_s = addr.rsplit(":", 1)
        infos = socket.getaddrinfo(
            host, int(port_s), socket.AF_INET, socket.SOCK_STREAM
        )
        if not infos:
            raise ValueError("unresolvable")
        sockaddr = infos[0][4]
        if not is_resolved_ip_allowed(sockaddr[0]):
            raise ValueError("address not allowed")
        sock = socket.create_connection(sockaddr, timeout=CONNECT_TIMEOUT_S)
        sock.settimeout(None)
        self._add_peer(sock, addr)

    def broadcast(self, type_name: str, data: Any) -> str:
        env = Envelope.build(type_name, data)
        if env.is_control():
            raise ProtocolError("broadcast is the gossip path")
        with self.lock:
            fresh = self.dedup.should_process(env)
            if fresh:
                self._record(env)
            peers = list(self.peers)
        if fresh:
            for peer in peers:
                self._write(peer, env)
            self._send_udp(env)
            self.on_app(type_name, data)
        return env.id

    def send(self, addr: str, type_name: str, data: Any) -> str:
        """Write one control-path envelope to a single peer. Do not relay."""
        env = Envelope.build(type_name, data)
        if not env.is_control():
            raise ProtocolError("send is the control path")
        with self.lock:
            match = next((peer for peer in self.peers if peer.addr == addr), None)
        if match is None:
            raise ProtocolError("no such link")
        self._write(match, env)
        return env.id

    def _record(self, env: Envelope) -> None:
        if len(self.received) >= MAX_RECEIVED:
            self.received.pop(0)
        self.received.append({"id": env.id, "type": env.type, "data": env.data})

    def ids(self) -> List[str]:
        with self.lock:
            return [item["id"] for item in self.received]

    def close(self) -> None:
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        if self._udp is not None:
            try:
                self._udp.close()
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
            if len(self.peers) >= MAX_PEERS:
                try:
                    sock.close()
                except OSError:
                    pass
                return
            self.peers.append(peer)
        self._write(
            peer, control.hello(self.impl, caps=self._caps(), listen=self.listen_addr)
        )
        threading.Thread(target=self._read_loop, args=(peer,), daemon=True).start()

    def _write(self, peer: _Peer, env: Envelope) -> None:
        frame = encode_frame(env.to_bytes())
        with peer.lock:
            peer.sock.sendall(frame)

    def _read_loop(self, peer: _Peer) -> None:
        reader = FrameReader(max_frame_bytes=NODE_MAX_FRAME)
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
        if env.type.startswith("ctl."):
            if env.type == control.HELLO:
                hello = control.parse_hello(env)
                peer.impl = hello["impl"]
                self.on_event(
                    {"event": "hello", "peer": hello["impl"], "addr": peer.addr}
                )
            return
        if env.is_control():
            self.on_link(peer.addr, env.type, env.data)
            return
        if not self.allow_peer(peer.addr):
            return
        with self.lock:
            if not self.dedup.should_process(env):
                return
            self._record(env)
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
            self._send_udp(env)
        self.on_app(env.type, env.data)

    def _caps(self) -> List[str]:
        return hello_caps(self._udp is not None)

    def _connect_udp(self, host_port: str) -> None:
        if not is_connect_allowed(host_port):
            raise ValueError("address not allowed")
        self.bind_udp()
        with self.lock:
            if host_port not in self._udp_peers:
                if len(self.peers) + len(self._udp_peers) >= MAX_PEERS:
                    raise ValueError("too many peers")
                self._udp_peers.append(host_port)
        env = control.hello(
            self.impl,
            caps=self._caps(),
            listen=self.listen_addr or None,
        )
        assert self._udp is not None
        self._udp.send(host_port, env.to_bytes())

    def _send_udp(self, env: Envelope, skip: str = "") -> None:
        if self._udp is None:
            return
        body = env.to_bytes()
        if len(body) > MAX_UDP_BYTES:
            return
        with self.lock:
            peers = list(self._udp_peers)
        for host_port in peers:
            if host_port == skip:
                continue
            try:
                self._udp.send(host_port, body)
            except OSError:
                pass

    def _udp_loop(self) -> None:
        assert self._udp is not None
        while True:
            try:
                src, body = self._udp.recv()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                self._handle_datagram(src, body)
            except (ProtocolError, ValueError) as exc:
                self.on_event({"event": "error", "message": str(exc), "addr": src})

    def _handle_datagram(self, src: str, body: bytes) -> None:
        if len(body) > MAX_UDP_BYTES:
            return
        env = Envelope.parse(body)
        with self.lock:
            if (
                src not in self._udp_peers
                and len(self.peers) + len(self._udp_peers) < MAX_PEERS
            ):
                self._udp_peers.append(src)
        if env.type.startswith("ctl."):
            if env.type == control.HELLO:
                hello = control.parse_hello(env)
                self.on_event({"event": "hello", "peer": hello["impl"], "addr": src})
            return
        if env.is_control():
            self.on_link(src, env.type, env.data)
            return
        if not self.allow_peer(src):
            return
        with self.lock:
            if not self.dedup.should_process(env):
                return
            self._record(env)
            should_relay = self.dedup.should_relay(env)
            peers = list(self.peers)
        self.on_event(
            {"event": "received", "id": env.id, "type": env.type, "data": env.data}
        )
        if should_relay:
            for other in peers:
                try:
                    self._write(other, env)
                except OSError:
                    pass
            self._send_udp(env, skip=src)
        self.on_app(env.type, env.data)

    def _drop(self, peer: _Peer) -> None:
        with self.lock:
            if peer in self.peers:
                self.peers.remove(peer)
        try:
            peer.sock.close()
        except OSError:
            pass


def emit(event: Dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        sys.stdout.write(json.dumps(event, separators=(",", ":")) + "\n")
        sys.stdout.flush()
