"""chaincraft — Level 0 wire protocol and Level 1 object semantics.

Implements SPEC/wire-v1.md and SPEC/semantics-v1.md. Consensus, ledgers, storage
and the application layer are Level 2 and live in their own modules.
"""

from .canonical import (
    CanonicalError,
    canonical_bytes,
    canonical_json,
    parse_json,
    payload_digest,
)
from .control import CONTROL_TYPES
from .dedup import DEFAULT_CAPACITY, Deduplicator, SeenDigests
from .envelope import PROTOCOL_VERSION, Envelope, ProtocolError
from .framing import (
    MAX_FRAME_BYTES,
    MAX_UDP_BYTES,
    FrameReader,
    FramingError,
    decode_datagram,
    encode_datagram,
    encode_frame,
)
from .memento import StateMemento
from .object import SharedObject, frontier_digest, merkle_digest, wins_replacement
from .pipeline import ApplyResult, ObjectRegistry

__version__ = "1.7.0"
WIRE_VERSION = PROTOCOL_VERSION
IMPL = f"py-chaincraft/{__version__}"

__all__ = [
    "__version__",
    "WIRE_VERSION",
    "IMPL",
    "PROTOCOL_VERSION",
    # errors
    "CanonicalError",
    "ProtocolError",
    "FramingError",
    # level 0
    "canonical_json",
    "canonical_bytes",
    "parse_json",
    "payload_digest",
    "Envelope",
    "FrameReader",
    "encode_frame",
    "encode_datagram",
    "decode_datagram",
    "MAX_FRAME_BYTES",
    "MAX_UDP_BYTES",
    "CONTROL_TYPES",
    "SeenDigests",
    "Deduplicator",
    "DEFAULT_CAPACITY",
    # level 1
    "StateMemento",
    "SharedObject",
    "ObjectRegistry",
    "ApplyResult",
    "merkle_digest",
    "frontier_digest",
    "wins_replacement",
]
