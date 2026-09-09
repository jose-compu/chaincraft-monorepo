"""Pedagogical BitTorrent swarm — SPEC/features/bittorrent-swarm.md."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Dict, List, Optional, Set

from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = [
    "Swarm",
    "WIRE_TYPE",
    "MAX_TORRENTS",
    "MAX_PIECES",
    "MAX_PIECE_BYTES",
    "MAX_SEED_BYTES",
    "info_hash",
    "piece_hash",
    "split_payload",
    "BitTorrentClient",
]

WIRE_TYPE = "app.bittorrent"
MAX_TORRENTS = 8
MAX_PIECES = 64
MAX_PIECE_BYTES = 65536
MAX_NAME_LEN = 64
MAX_PEER_ID_LEN = 64
MAX_HAVE_PEERS = 32
MAX_SEED_BYTES = MAX_PIECES * MAX_PIECE_BYTES
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX = re.compile(r"^(?:[0-9a-f]{2})+$")


def piece_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def info_hash(name: str, pieces: List[str]) -> str:
    return merkle_digest({"name": name, "pieces": pieces})


def split_payload(name: str, text: str, piece_size: int) -> Dict[str, Any]:
    if not name or not text or piece_size < 1:
        raise ValueError("name and data must be non-empty; piece_size >= 1")
    if len(name) > MAX_NAME_LEN or piece_size > MAX_PIECE_BYTES:
        raise ValueError("name or piece_size exceeds the prototype limit")
    raw = text.encode("utf-8")
    if len(raw) > MAX_SEED_BYTES:
        raise ValueError("payload exceeds the prototype limit")
    if (len(raw) + piece_size - 1) // piece_size > MAX_PIECES:
        raise ValueError("too many pieces")
    chunks = [raw[i : i + piece_size] for i in range(0, len(raw), piece_size)]
    hashes = [piece_hash(chunk) for chunk in chunks]
    payloads = [chunk.hex() for chunk in chunks]
    return {
        "info_hash": info_hash(name, hashes),
        "length": len(raw),
        "payloads": payloads,
        "pieces": hashes,
    }


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


class _Torrent:
    def __init__(self, name: str, pieces: List[str]) -> None:
        self.name = name
        self.pieces = pieces
        self.data: Dict[int, str] = {}
        self.have: Dict[str, Set[int]] = {}

    def mark(self, peer: str, index: int) -> None:
        self.have.setdefault(peer, set()).add(index)


class Swarm(SharedObject):
    def __init__(self) -> None:
        self._torrents: Dict[str, _Torrent] = {}

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        parsed = self._parse(message)
        if parsed is None:
            return self.emit_state_memento()
        kind = parsed[0]
        if kind == "metainfo":
            _, name, pieces, digest = parsed
            if digest not in self._torrents:
                self._torrents[digest] = _Torrent(name, pieces)
        elif kind == "have":
            _, digest, peer, index = parsed
            self._torrents[digest].mark(peer, index)
        elif kind == "piece":
            _, digest, peer, index, data = parsed
            torrent = self._torrents[digest]
            torrent.data[index] = data
            torrent.mark(peer, index)
        return self.emit_state_memento()

    def emit_state_memento(self) -> StateMemento:
        return StateMemento.normalize(merkle_digest({"torrents": self._snapshot(), "v": 1}), [])

    def get_state_digests(self) -> list:
        digest = self.emit_state_memento().canonical_digest
        return [digest] if digest else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        return {"torrents": self._snapshot(), "v": 1}

    def assembled(self, digest: str) -> Optional[str]:
        torrent = self._torrents.get(digest)
        if torrent is None:
            return None
        if any(index not in torrent.data for index in range(len(torrent.pieces))):
            return None
        raw = b"".join(bytes.fromhex(torrent.data[index]) for index in range(len(torrent.pieces)))
        return raw.hex()

    def missing(self, digest: str) -> List[int]:
        torrent = self._torrents.get(digest)
        if torrent is None:
            return []
        return [index for index in range(len(torrent.pieces)) if index not in torrent.data]

    def piece_hex(self, digest: str, index: int) -> Optional[str]:
        torrent = self._torrents.get(digest)
        if torrent is None:
            return None
        return torrent.data.get(index)

    def known(self) -> List[str]:
        return sorted(self._torrents)

    def _snapshot(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for digest in sorted(self._torrents):
            torrent = self._torrents[digest]
            count = len(torrent.pieces)
            have = {
                peer: sorted(indices)
                for peer, indices in sorted(torrent.have.items())
            }
            complete = [peer for peer, indices in have.items() if indices == list(range(count))]
            out[digest] = {
                "complete": complete,
                "data": {str(index): torrent.data[index] for index in sorted(torrent.data)},
                "have": have,
                "name": torrent.name,
                "pieces": list(torrent.pieces),
            }
        return out

    def _parse(self, message: Any) -> Optional[tuple]:
        if not isinstance(message, dict):
            return None
        kind = message.get("bt")
        if kind == "metainfo":
            name = message.get("name")
            pieces = message.get("pieces")
            if not isinstance(name, str) or not name or len(name) > MAX_NAME_LEN:
                return None
            if not isinstance(pieces, list) or not pieces or len(pieces) > MAX_PIECES:
                return None
            if any(not _hex64(item) for item in pieces):
                return None
            digest = info_hash(name, list(pieces))
            existing = self._torrents.get(digest)
            if existing is not None and (existing.name != name or existing.pieces != pieces):
                return None
            if existing is None and len(self._torrents) >= MAX_TORRENTS:
                return None
            return ("metainfo", name, list(pieces), digest)
        if kind in {"have", "piece", "request"}:
            digest = message.get("info_hash")
            peer = message.get("peer")
            index = message.get("index")
            torrent = self._torrents.get(digest) if _hex64(digest) else None
            if torrent is None or not isinstance(peer, str) or not peer:
                return None
            if len(peer) > MAX_PEER_ID_LEN:
                return None
            if not _is_int(index) or index < 0 or index >= len(torrent.pieces):
                return None
            if kind != "request" and peer not in torrent.have and len(torrent.have) >= MAX_HAVE_PEERS:
                return None
            if kind != "piece":
                return (kind, digest, peer, index)
            data = message.get("data")
            if not isinstance(data, str) or len(data) > MAX_PIECE_BYTES * 2:
                return None
            if not _HEX.fullmatch(data):
                return None
            if piece_hash(bytes.fromhex(data)) != torrent.pieces[index]:
                return None
            return ("piece", digest, peer, index, data)
        return None


class BitTorrentClient:
    """Binds `Swarm` to a mesh `broadcast` hook — not part of the wire node."""

    def __init__(self, broadcast: Callable[[str, Any], str]) -> None:
        self.swarm = Swarm()
        self.local_peer = ""
        self._broadcast = broadcast

    def on_app(self, type_name: str, data: Any) -> None:
        if type_name != WIRE_TYPE:
            return
        if self.swarm.is_valid(data):
            self.swarm.add_message(data)
        self._serve_request(data)

    def handle_command(self, cmd: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        name = cmd.get("cmd")
        if name == "bt.seed":
            return self.seed(str(cmd["peer"]), str(cmd["name"]), cmd["data"], cmd["piece_size"])
        if name == "bt.leech":
            return self.leech(str(cmd["peer"]), cmd.get("info_hash"))
        if name == "bt.status":
            return self.status()
        return None

    def seed(self, peer: str, name: str, data: Any, piece_size: Any) -> Dict[str, Any]:
        if len(peer) > MAX_PEER_ID_LEN or len(name) > MAX_NAME_LEN:
            raise ValueError("peer or name exceeds the prototype limit")
        if piece_size is True or piece_size is False:
            raise ValueError("invalid piece_size")
        if not isinstance(data, str):
            raise ValueError("data must be a string")
        self.local_peer = peer
        split = split_payload(name, data, int(piece_size))
        self._broadcast(WIRE_TYPE, {"bt": "metainfo", "name": name, "pieces": split["pieces"]})
        for index, payload in enumerate(split["payloads"]):
            self._broadcast(
                WIRE_TYPE,
                {
                    "bt": "piece",
                    "data": payload,
                    "index": index,
                    "info_hash": split["info_hash"],
                    "peer": peer,
                },
            )
        return {
            "event": "bt.seeded",
            "info_hash": split["info_hash"],
            "length": split["length"],
            "pieces": len(split["pieces"]),
        }

    def leech(self, peer: str, info_hash_value: Any = None) -> Dict[str, Any]:
        if len(peer) > MAX_PEER_ID_LEN:
            raise ValueError("peer exceeds the prototype limit")
        self.local_peer = peer
        known = self.swarm.known()
        digest = info_hash_value if isinstance(info_hash_value, str) else (known[0] if known else "")
        requested: List[int] = []
        if digest:
            for index in self.swarm.missing(digest):
                self._broadcast(
                    WIRE_TYPE,
                    {"bt": "request", "index": index, "info_hash": digest, "peer": peer},
                )
                requested.append(index)
        return {"event": "bt.leech", "info_hash": digest, "requested": requested}

    def status(self) -> Dict[str, Any]:
        snap = self.swarm.state()["torrents"]
        torrents = []
        for digest in self.swarm.known():
            entry = snap[digest]
            torrents.append(
                {
                    "assembled": self.swarm.assembled(digest),
                    "complete": entry["complete"],
                    "have": entry["have"],
                    "info_hash": digest,
                    "name": entry["name"],
                }
            )
        return {"event": "bt.status", "torrents": torrents}

    def _serve_request(self, data: Any) -> None:
        if not isinstance(data, dict) or data.get("bt") != "request" or not self.local_peer:
            return
        digest = data.get("info_hash")
        index = data.get("index")
        if not isinstance(digest, str) or not isinstance(index, int) or index is True or index is False:
            return
        payload = self.swarm.piece_hex(digest, index)
        if payload is None:
            return
        self._broadcast(
            WIRE_TYPE,
            {
                "bt": "piece",
                "data": payload,
                "index": index,
                "info_hash": digest,
                "peer": self.local_peer,
            },
        )
