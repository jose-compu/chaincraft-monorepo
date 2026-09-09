//! chaincraft-core — Level 0 wire protocol and Level 1 object semantics.
//!
//! Implements SPEC/wire-v1.md and SPEC/semantics-v1.md.

pub mod canonical;
pub mod control;
pub mod crypto;
pub mod dedup;
pub mod envelope;
pub mod error;
pub mod features;
pub mod framing;
pub mod memento;
pub mod object;
pub mod pipeline;

pub use canonical::{
    bytes_to_hex, canonical_bytes, canonical_json, hex_to_bytes, parse_json, payload_digest,
    JsonValue, MAX_DEPTH, MAX_SAFE_INT, MIN_SAFE_INT,
};
pub use dedup::{Deduplicator, SeenDigests, DEFAULT_CAPACITY};
pub use envelope::{Envelope, MAX_FUTURE_SKEW_MS, PROTOCOL_VERSION};
pub use error::{Error, Result};
pub use framing::{
    decode_datagram, encode_datagram, encode_frame, FrameReader, MAX_FRAME_BYTES, MAX_UDP_BYTES,
};
pub use memento::StateMemento;
pub use object::{frontier_digest, merkle_digest, wins_replacement, ApplicationObject};
pub use pipeline::{ApplyResult, ObjectRegistry};
