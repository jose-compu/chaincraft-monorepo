//! StateMemento — SPEC/semantics-v1.md §4.

use std::collections::{BTreeMap, BTreeSet};

use crate::canonical::JsonValue;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StateMemento {
    pub canonical_digest: String,
    pub frontier_digests: Vec<String>,
    pub revision: i64,
    pub metadata: BTreeMap<String, JsonValue>,
}

impl StateMemento {
    pub fn new(
        canonical_digest: impl Into<String>,
        frontier_digests: Vec<String>,
        revision: i64,
        metadata: BTreeMap<String, JsonValue>,
    ) -> Self {
        Self {
            canonical_digest: canonical_digest.into(),
            frontier_digests,
            revision,
            metadata,
        }
    }

    /// Build a normalized memento — §4.1.
    pub fn normalize(canonical_digest: &str, frontier_digests: &[String]) -> Self {
        let mut collected: BTreeSet<String> = frontier_digests
            .iter()
            .filter(|h| !h.is_empty())
            .cloned()
            .collect();
        if !canonical_digest.is_empty() {
            collected.insert(canonical_digest.to_string());
        }
        Self {
            canonical_digest: canonical_digest.to_string(),
            frontier_digests: collected.into_iter().collect(),
            revision: 0,
            metadata: BTreeMap::new(),
        }
    }

    /// Whether the head moved to a branch that does not build on `previous` — §4.2.
    pub fn indicates_reorg_against(&self, previous: Option<&StateMemento>) -> bool {
        let Some(previous) = previous else {
            return false;
        };
        if self.canonical_digest.is_empty() || previous.canonical_digest.is_empty() {
            return false;
        }
        if self.canonical_digest == previous.canonical_digest {
            return false;
        }
        !self
            .frontier_digests
            .iter()
            .any(|d| d == &previous.canonical_digest)
    }

    pub fn to_object(&self) -> JsonValue {
        JsonValue::object([
            (
                "canonical_digest".into(),
                JsonValue::String(self.canonical_digest.clone()),
            ),
            (
                "frontier_digests".into(),
                JsonValue::Array(
                    self.frontier_digests
                        .iter()
                        .map(|d| JsonValue::String(d.clone()))
                        .collect(),
                ),
            ),
            ("revision".into(), JsonValue::Number(self.revision)),
            ("metadata".into(), JsonValue::Object(self.metadata.clone())),
        ])
    }
}
