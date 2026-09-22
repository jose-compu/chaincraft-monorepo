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

    fn is_valid(&self, _message: &JsonValue) -> bool {
        true
    }

    /// Local apply. A prototype overrides this and nothing else.
    fn receive(&mut self, _message: &JsonValue) {}

    fn add_message(
        &mut self,
        message: &JsonValue,
        _frontier_state: Option<&StateMemento>,
    ) -> Option<StateMemento> {
        self.receive(message);
        None
    }

    fn emit_state_memento(&self) -> StateMemento {
        StateMemento::normalize("", &[])
    }
    fn get_state_digests(&self) -> Vec<String> {
        Vec::new()
    }
    fn is_merkelized(&self) -> bool {
        false
    }
}

/// A local protocol. Implement `receive`. Peers may miss messages.
///
/// This supplies `ApplicationObject`. Consensus objects implement
/// `ApplicationObject` directly so they can return a memento.
pub trait Protocol: Any {
    fn accept(&self, _message: &JsonValue) -> bool {
        true
    }

    fn receive(&mut self, _message: &JsonValue) {}
}

impl<T: Protocol> ApplicationObject for T {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn is_valid(&self, message: &JsonValue) -> bool {
        Protocol::accept(self, message)
    }

    fn receive(&mut self, message: &JsonValue) {
        Protocol::receive(self, message)
    }

    fn add_message(
        &mut self,
        message: &JsonValue,
        _frontier_state: Option<&StateMemento>,
    ) -> Option<StateMemento> {
        Protocol::receive(self, message);
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pipeline::ObjectRegistry;

    struct Room {
        lines: Vec<String>,
    }

    impl Protocol for Room {
        fn receive(&mut self, message: &JsonValue) {
            let text = message
                .as_object()
                .and_then(|obj| obj.get("text"))
                .and_then(|value| value.as_str())
                .unwrap_or("")
                .to_owned();
            self.lines.push(text);
        }
    }

    #[test]
    fn prototype_only_implements_receive() {
        let mut room = Room { lines: Vec::new() };
        let message = JsonValue::object([("text".into(), JsonValue::String("hi".into()))]);
        assert!(room.is_valid(&message));
        assert!(room.add_message(&message, None).is_none());
        assert_eq!(room.lines, ["hi".to_owned()]);
        assert!(!room.is_merkelized());
        assert!(room.get_state_digests().is_empty());
        assert!(room.emit_state_memento().canonical_digest.is_empty());

        let mut registry = ObjectRegistry::new();
        registry.register("room", Box::new(Room { lines: Vec::new() }));
        let hello = JsonValue::object([("text".into(), JsonValue::String("hello".into()))]);
        let result = registry.apply(&hello);
        assert!(result.accepted);
        let memo = &result.mementos["room"];
        assert!(memo.canonical_digest.is_empty());
        assert!(memo.frontier_digests.is_empty());
        let applied = registry
            .get("room")
            .unwrap()
            .as_any()
            .downcast_ref::<Room>()
            .unwrap();
        assert_eq!(applied.lines, ["hello".to_owned()]);
    }
}
