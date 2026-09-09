//! Deduplication and relay — SPEC/wire-v1.md §7.

use indexmap::IndexSet;

use crate::envelope::Envelope;

pub const DEFAULT_CAPACITY: usize = 100_000;

/// Bounded set of seen payload digests, evicting the oldest insertion first.
///
/// `IndexSet` is insertion-ordered and leaves that order undisturbed on a
/// repeat insert, which is the no-refresh rule in §7.2.
#[derive(Debug)]
pub struct SeenDigests {
    digests: IndexSet<String>,
    pub capacity: usize,
}

impl SeenDigests {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity >= 1, "capacity must be a positive integer");
        Self {
            digests: IndexSet::new(),
            capacity,
        }
    }

    pub fn contains(&self, digest: &str) -> bool {
        self.digests.contains(digest)
    }

    /// Record a digest. Returns false when it was already present.
    pub fn add(&mut self, digest: impl Into<String>) -> bool {
        let digest = digest.into();
        if self.digests.contains(&digest) {
            return false;
        }
        if self.digests.len() >= self.capacity {
            self.digests.shift_remove_index(0);
        }
        self.digests.insert(digest);
        true
    }

    pub fn len(&self) -> usize {
        self.digests.len()
    }

    pub fn is_empty(&self) -> bool {
        self.digests.is_empty()
    }

    pub fn clear(&mut self) {
        self.digests.clear();
    }
}

/// The receive-path gate.
pub struct Deduplicator {
    pub seen: SeenDigests,
}

impl Deduplicator {
    pub fn new(capacity: usize) -> Self {
        Self {
            seen: SeenDigests::new(capacity),
        }
    }

    pub fn should_process(&mut self, envelope: &Envelope) -> bool {
        if envelope.is_control() {
            return true;
        }
        self.seen.add(envelope.id.clone())
    }

    pub fn should_relay(&self, envelope: &Envelope) -> bool {
        !envelope.is_control()
    }
}

impl Default for Deduplicator {
    fn default() -> Self {
        Self::new(DEFAULT_CAPACITY)
    }
}
