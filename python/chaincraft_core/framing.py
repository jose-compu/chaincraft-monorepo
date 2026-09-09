"""TCP framing — SPEC/wire-v1.md section 4.

    [u32 big-endian length][canonical JSON body]
"""

from __future__ import annotations

from typing import Iterator, List, Optional

__all__ = [
    "FramingError",
    "MAX_FRAME_BYTES",
    "MAX_UDP_BYTES",
    "encode_frame",
    "encode_datagram",
    "decode_datagram",
    "FrameReader",
]

MAX_FRAME_BYTES = 16777216  # 16 MiB
MAX_UDP_BYTES = 65507


class FramingError(ValueError):
    """Frame violates the wire framing rules."""


def encode_frame(body: bytes) -> bytes:
    """Prefix ``body`` with its big-endian u32 length."""
    if not body:
        raise FramingError("zero-length frame is invalid")
    if len(body) > MAX_FRAME_BYTES:
        raise FramingError(f"frame of {len(body)} bytes exceeds {MAX_FRAME_BYTES}")
    return len(body).to_bytes(4, "big") + body


def encode_datagram(body: bytes) -> bytes:
    """One envelope per datagram, no length prefix — wire-v1.md section 4.2.

    A datagram carries its own length, so the TCP prefix would be redundant.
    """
    if not body:
        raise FramingError("zero-length datagram is invalid")
    if len(body) > MAX_UDP_BYTES:
        raise FramingError(f"datagram of {len(body)} bytes exceeds {MAX_UDP_BYTES}")
    return body


def decode_datagram(data: bytes) -> bytes:
    """Validate a received datagram and return its body."""
    if not data:
        raise FramingError("zero-length datagram is invalid")
    if len(data) > MAX_UDP_BYTES:
        raise FramingError(f"datagram of {len(data)} bytes exceeds {MAX_UDP_BYTES}")
    return bytes(data)


class FrameReader:
    """Reassembles frames from an arbitrarily chunked byte stream.

    A TCP read boundary has nothing to do with a frame boundary, so callers feed
    whatever ``recv`` returned and drain whole frames as they complete.
    """

    def __init__(self, max_frame_bytes: int = MAX_FRAME_BYTES) -> None:
        self.max_frame_bytes = max_frame_bytes
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> List[bytes]:
        """Append ``chunk`` and return every frame that is now complete."""
        self._buf.extend(chunk)
        return list(self._drain())

    def _drain(self) -> Iterator[bytes]:
        while True:
            if len(self._buf) < 4:
                return
            length = int.from_bytes(self._buf[:4], "big")
            if length == 0:
                raise FramingError("zero-length frame is invalid")
            if length > self.max_frame_bytes:
                raise FramingError(
                    f"declared length {length} exceeds {self.max_frame_bytes}"
                )
            if len(self._buf) < 4 + length:
                return
            body = bytes(self._buf[4 : 4 + length])
            del self._buf[: 4 + length]
            yield body

    @property
    def pending(self) -> int:
        """Bytes buffered but not yet forming a complete frame."""
        return len(self._buf)
