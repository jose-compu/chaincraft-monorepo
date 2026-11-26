//! PBFT object — SPEC/features/consensus-pbft.md.

use std::any::Any;
use std::collections::HashMap;

use crate::canonical::JsonValue;
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};

pub const DEFAULT_REPLICAS: &[&str] = &["r0", "r1", "r2", "r3"];

fn is_hex64(text: &str) -> bool {
    text.len() == 64 && text.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

#[derive(Clone, Debug)]
pub struct Executed {
    pub digest: String,
    pub seq: i64,
}

#[derive(Debug)]
pub struct Pbft {
    replicas: Vec<String>,
    n: usize,
    quorum: usize,
    view: i64,
    sequence: i64,
    digest: String,
    prepares: HashMap<String, String>,
    commits: HashMap<String, String>,
    executed: Vec<Executed>,
}

impl Pbft {
    pub fn new(replicas: &[&str]) -> Result<Self, String> {
        if replicas.is_empty() {
            return Err("replicas must be unique non-empty ids".into());
        }
        let mut names: Vec<String> = replicas.iter().map(|s| (*s).to_owned()).collect();
        names.sort();
        if names.iter().any(|n| n.is_empty()) || names.windows(2).any(|w| w[0] == w[1]) {
            return Err("replicas must be unique non-empty ids".into());
        }
        let n = names.len();
        let f = (n - 1) / 3;
        Ok(Self {
            replicas: names,
            n,
            quorum: 2 * f + 1,
            view: 0,
            sequence: 1,
            digest: String::new(),
            prepares: HashMap::new(),
            commits: HashMap::new(),
            executed: Vec::new(),
        })
    }

    pub fn default_set() -> Self {
        Self::new(DEFAULT_REPLICAS).expect("defaults")
    }

    pub fn primary_for(&self, view: i64) -> &str {
        &self.replicas[(view as usize) % self.n]
    }

    pub fn sequence_no(&self) -> i64 {
        self.sequence
    }

    pub fn quorum_size(&self) -> usize {
        self.quorum
    }

    pub fn replica_list(&self) -> &[String] {
        &self.replicas
    }

    pub fn state(&self) -> (i64, i64, usize, usize, Vec<(String, i64)>) {
        (
            self.view,
            self.sequence,
            self.count(&self.prepares),
            self.count(&self.commits),
            self.executed
                .iter()
                .map(|item| (item.digest.clone(), item.seq))
                .collect(),
        )
    }

    fn count(&self, votes: &HashMap<String, String>) -> usize {
        votes.values().filter(|d| *d == &self.digest).count()
    }

    fn parse<'a>(&self, message: &'a JsonValue) -> Option<(&'a str, i64, i64, &'a str, &'a str)> {
        let obj = message.as_object()?;
        if obj.get("consensus").and_then(JsonValue::as_str) != Some("pbft") {
            return None;
        }
        let phase = obj.get("phase").and_then(JsonValue::as_str)?;
        if !matches!(phase, "pre-prepare" | "prepare" | "commit") {
            return None;
        }
        let view = obj.get("view").and_then(JsonValue::as_i64)?;
        let sequence = obj.get("sequence").and_then(JsonValue::as_i64)?;
        let digest = obj.get("digest").and_then(JsonValue::as_str)?;
        let replica = obj.get("replica").and_then(JsonValue::as_str)?;
        if view < 0 || sequence < 1 || !is_hex64(digest) {
            return None;
        }
        if !self.replicas.iter().any(|r| r == replica) {
            return None;
        }
        if phase == "pre-prepare" {
            let value = obj.get("value").and_then(JsonValue::as_str)?;
            let want = merkle_digest(&JsonValue::String(value.to_owned())).expect("canonical");
            if digest != want || replica != self.primary_for(view) {
                return None;
            }
        }
        Some((phase, view, sequence, digest, replica))
    }
}

impl ApplicationObject for Pbft {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn is_valid(&self, message: &JsonValue) -> bool {
        self.parse(message).is_some()
    }

    fn add_message(
        &mut self,
        message: &JsonValue,
        _frontier_state: Option<&StateMemento>,
    ) -> Option<StateMemento> {
        if let Some((phase, view, sequence, digest, replica)) = self.parse(message) {
            if view == self.view && sequence == self.sequence {
                if phase == "pre-prepare" {
                    if self.digest.is_empty() {
                        self.digest = digest.to_owned();
                    }
                } else if self.digest.is_empty() || digest != self.digest {
                    return Some(self.emit_state_memento());
                } else if phase == "prepare" {
                    self.prepares
                        .entry(replica.to_owned())
                        .or_insert_with(|| digest.to_owned());
                } else {
                    self.commits
                        .entry(replica.to_owned())
                        .or_insert_with(|| digest.to_owned());
                }
                if !self.digest.is_empty()
                    && self.count(&self.prepares) >= self.quorum
                    && self.count(&self.commits) >= self.quorum
                {
                    self.executed.push(Executed {
                        digest: self.digest.clone(),
                        seq: self.sequence,
                    });
                    self.sequence += 1;
                    self.digest.clear();
                    self.prepares.clear();
                    self.commits.clear();
                }
            }
        }
        Some(self.emit_state_memento())
    }

    fn emit_state_memento(&self) -> StateMemento {
        let executed = JsonValue::Array(
            self.executed
                .iter()
                .map(|item| JsonValue::String(item.digest.clone()))
                .collect(),
        );
        let payload = JsonValue::object([
            ("executed".into(), executed),
            ("sequence".into(), JsonValue::Number(self.sequence)),
            ("v".into(), JsonValue::Number(1)),
        ]);
        let digest = merkle_digest(&payload).expect("canonical");
        StateMemento::normalize(&digest, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        let head = self.emit_state_memento().canonical_digest;
        if head.is_empty() {
            Vec::new()
        } else {
            vec![head]
        }
    }

    fn is_merkelized(&self) -> bool {
        true
    }
}
