//! Proof-of-authority object — SPEC/features/consensus-poa.md.

use std::any::Any;
use std::collections::{HashMap, HashSet};

use crate::canonical::JsonValue;
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};

#[derive(Clone, Debug)]
struct Stored {
    height: i64,
    parent: String,
}

#[derive(Debug)]
pub struct ProofOfAuthority {
    authorities: Vec<String>,
    blocks: HashMap<String, Stored>,
    order: Vec<String>,
}

impl ProofOfAuthority {
    pub fn new(authorities: &[String]) -> Result<Self, String> {
        if authorities.is_empty() {
            return Err("authorities must be non-empty".into());
        }
        let mut seen = HashSet::new();
        for authority in authorities {
            if authority.is_empty() {
                return Err("each authority must be a non-empty string".into());
            }
            if !seen.insert(authority.clone()) {
                return Err("authorities must be distinct".into());
            }
        }
        Ok(Self {
            authorities: authorities.to_vec(),
            blocks: HashMap::new(),
            order: Vec::new(),
        })
    }

    pub fn state(&self) -> (Vec<String>, Vec<String>, i64, String) {
        let (tip, height) = self.tip();
        (self.order.clone(), self.canonical(&tip), height, tip)
    }

    fn tip(&self) -> (String, i64) {
        let mut best = String::new();
        let mut best_height = 0;
        for (digest, record) in &self.blocks {
            if record.height > best_height
                || (record.height == best_height && (best.is_empty() || digest < &best))
            {
                best = digest.clone();
                best_height = record.height;
            }
        }
        (best, best_height)
    }

    fn canonical(&self, tip: &str) -> Vec<String> {
        let mut chain = Vec::new();
        let mut cursor = tip.to_owned();
        while !cursor.is_empty() {
            let parent = self.blocks[&cursor].parent.clone();
            chain.push(cursor);
            cursor = parent;
        }
        chain.reverse();
        chain
    }

    fn parse(&self, message: &JsonValue) -> Option<(String, Stored)> {
        let obj = message.as_object()?;
        if obj.get("consensus").and_then(JsonValue::as_str) != Some("poa") {
            return None;
        }
        let height = obj.get("height").and_then(JsonValue::as_i64)?;
        let proposer = obj.get("proposer").and_then(JsonValue::as_str)?;
        let parent = obj.get("parent").and_then(JsonValue::as_str)?;
        let payload = obj.get("payload").and_then(JsonValue::as_str)?;
        if height < 1 || proposer.is_empty() || payload.is_empty() {
            return None;
        }
        if proposer != proposer_for(height, &self.authorities) {
            return None;
        }
        if parent.is_empty() {
            if height != 1 {
                return None;
            }
        } else {
            let prior = self.blocks.get(parent)?;
            if height != prior.height + 1 {
                return None;
            }
        }
        let digest = block_id(height, parent, payload, proposer);
        if self.blocks.contains_key(&digest) {
            return None;
        }
        Some((
            digest,
            Stored {
                height,
                parent: parent.to_owned(),
            },
        ))
    }
}

pub fn proposer_for(height: i64, authorities: &[String]) -> &str {
    let index = ((height - 1).rem_euclid(authorities.len() as i64)) as usize;
    &authorities[index]
}

pub fn block_id(height: i64, parent: &str, payload: &str, proposer: &str) -> String {
    let payload = JsonValue::object([
        ("height".into(), JsonValue::Number(height)),
        ("parent".into(), JsonValue::String(parent.to_owned())),
        ("payload".into(), JsonValue::String(payload.to_owned())),
        ("proposer".into(), JsonValue::String(proposer.to_owned())),
    ]);
    merkle_digest(&payload).expect("canonical")
}

impl ApplicationObject for ProofOfAuthority {
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
        if let Some((digest, record)) = self.parse(message) {
            self.blocks.insert(digest.clone(), record);
            self.order.push(digest);
        }
        Some(self.emit_state_memento())
    }

    fn emit_state_memento(&self) -> StateMemento {
        let (tip, height) = self.tip();
        let payload = JsonValue::object([
            ("height".into(), JsonValue::Number(height)),
            ("tip".into(), JsonValue::String(tip)),
            ("v".into(), JsonValue::Number(1)),
        ]);
        let digest = merkle_digest(&payload).expect("canonical");
        StateMemento::normalize(&digest, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        let (tip, _) = self.tip();
        if tip.is_empty() {
            Vec::new()
        } else {
            vec![tip]
        }
    }

    fn is_merkelized(&self) -> bool {
        true
    }
}
