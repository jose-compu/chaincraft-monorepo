//! chaincraft — Level 0 wire protocol and Level 1 object semantics.
//!
//! Implements SPEC/wire-v1.md and SPEC/semantics-v1.md.

pub mod adapters;
pub mod bittorrent;
pub mod canonical;
pub mod channel;
pub mod cli;
pub mod consensus_pbft;
pub mod consensus_pos;
pub mod consensus_pow;
pub mod control;
pub mod crypto;
pub mod dedup;
pub mod discovery;
pub mod ecdsa;
pub mod envelope;
pub mod error;
pub mod features;
pub mod fees;
pub mod framing;
pub mod ledger_balance;
pub mod ledger_utxo;
pub mod memento;
pub mod mempool;
pub mod mesh;
pub mod nat;
pub mod object;
pub mod peer;
pub mod pipeline;
pub mod pubsub;
pub mod storage;
pub mod stream;
pub mod vdf;
pub mod vrf;

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
pub use object::{frontier_digest, merkle_digest, wins_replacement, ApplicationObject, Protocol};
pub use pipeline::{ApplyResult, ObjectRegistry};
