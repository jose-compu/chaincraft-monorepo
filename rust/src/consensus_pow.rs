//! Proof-of-work object — SPEC/features/consensus-pow.md.

use std::any::Any;
use std::collections::HashMap;

use crate::canonical::JsonValue;
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};

pub const DEFAULT_DIFFICULTY: u32 = 2;

#[derive(Clone, Debug)]
struct Stored {
    height: i64,
    parent: String,
}

#[derive(Debug)]
pub struct ProofOfWork {
    difficulty: u32,
    blocks: HashMap<String, Stored>,
    order: Vec<String>,
}

impl ProofOfWork {
    pub fn new(difficulty: u32) -> Result<Self, String> {
        if !(1..=64).contains(&difficulty) {
            return Err("difficulty must be in 1..64".into());
        }
        Ok(Self {
            difficulty,
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
        if obj.get("consensus").and_then(JsonValue::as_str) != Some("pow") {
            return None;
        }
        let height = obj.get("height").and_then(JsonValue::as_i64)?;
        let nonce = obj.get("nonce").and_then(JsonValue::as_i64)?;
        let miner = obj.get("miner").and_then(JsonValue::as_str)?;
        let parent = obj.get("parent").and_then(JsonValue::as_str)?;
        let payload = obj.get("payload").and_then(JsonValue::as_str)?;
        if height < 1 || nonce < 0 || miner.is_empty() || payload.is_empty() {
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
        let digest = block_id(height, miner, nonce, parent, payload);
        if !meets_work(&digest, self.difficulty) || self.blocks.contains_key(&digest) {
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

pub fn block_id(height: i64, miner: &str, nonce: i64, parent: &str, payload: &str) -> String {
    let payload = JsonValue::object([
        ("height".into(), JsonValue::Number(height)),
        ("miner".into(), JsonValue::String(miner.to_owned())),
        ("nonce".into(), JsonValue::Number(nonce)),
        ("parent".into(), JsonValue::String(parent.to_owned())),
        ("payload".into(), JsonValue::String(payload.to_owned())),
    ]);
    merkle_digest(&payload).expect("canonical")
}

pub fn meets_work(digest: &str, difficulty: u32) -> bool {
    digest.len() >= difficulty as usize
        && digest.as_bytes()[..difficulty as usize]
            .iter()
            .all(|b| *b == b'0')
}

impl ApplicationObject for ProofOfWork {
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
