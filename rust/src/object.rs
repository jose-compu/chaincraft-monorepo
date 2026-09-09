//! Application object contract and digest helpers — SPEC/semantics-v1.md §2, §5, §6.

use std::any::Any;

use sha2::{Digest, Sha256};

use crate::canonical::{canonical_bytes, JsonValue};
use crate::error::Result;
use crate::memento::StateMemento;

pub const FRONTIER_FORMAT_VERSION: i64 = 1;

/// Merkelized object digest — §5.
pub fn merkle_digest(state_payload: &JsonValue) -> Result<String> {
    Ok(hex::encode(Sha256::digest(canonical_bytes(state_payload)?)))
}

/// Digest over a multi-head frontier — §5.1.
pub fn frontier_digest(heads: &[String]) -> Result<String> {
    let mut sorted: Vec<String> = heads.iter().filter(|h| !h.is_empty()).cloned().collect();
    sorted.sort();
    let payload = JsonValue::object([
        (
            "frontier_heads".into(),
            JsonValue::Array(sorted.into_iter().map(JsonValue::String).collect()),
        ),
        ("v".into(), JsonValue::Number(FRONTIER_FORMAT_VERSION)),
    ]);
    Ok(hex::encode(Sha256::digest(canonical_bytes(&payload)?)))
}

/// Whether a candidate entry replaces the incumbent — §6.1.
pub fn wins_replacement(
    candidate_rank: i64,
    candidate_digest: &str,
    incumbent_rank: i64,
    incumbent_digest: &str,
) -> bool {
    if candidate_rank > incumbent_rank {
        return true;
    }
    if candidate_rank < incumbent_rank {
        return false;
    }
    candidate_digest < incumbent_digest
}

/// The application object contract — §2.
pub trait ApplicationObject: Any {
    fn as_any(&self) -> &dyn Any;

    fn is_valid(&self, message: &JsonValue) -> bool;
    fn add_message(
        &mut self,
        message: &JsonValue,
        frontier_state: Option<&StateMemento>,
    ) -> Option<StateMemento>;
    fn emit_state_memento(&self) -> StateMemento;
    fn get_state_digests(&self) -> Vec<String> {
        Vec::new()
    }
    fn is_merkelized(&self) -> bool {
        false
    }
}
