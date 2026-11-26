//! Proof-of-elapsed-time object — SPEC/features/consensus-poet.md.

use std::any::Any;
use std::collections::HashMap;

use crate::canonical::JsonValue;
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};
use crate::vdf;

#[derive(Clone, Debug)]
struct Stored {
    wait: u32,
}

#[derive(Debug)]
pub struct ProofOfElapsedTime {
    seed_bytes: Vec<u8>,
    tickets: HashMap<String, Stored>,
    order: Vec<String>,
}

impl ProofOfElapsedTime {
    pub fn new(seed: &str) -> Result<Self, String> {
        if seed.is_empty() {
            return Err("seed must be a non-empty string".into());
        }
        Ok(Self {
            seed_bytes: seed.as_bytes().to_vec(),
            tickets: HashMap::new(),
            order: Vec::new(),
        })
    }

    pub fn seed_bytes(&self) -> &[u8] {
        &self.seed_bytes
    }

    pub fn state(&self) -> (Vec<String>, Vec<String>, u32, String) {
        let (winner, wait) = self.winner();
        let canonical = if winner.is_empty() {
            Vec::new()
        } else {
            vec![winner.clone()]
        };
        (canonical, self.order.clone(), wait, winner)
    }

    fn winner(&self) -> (String, u32) {
        let mut best = String::new();
        let mut best_wait = u32::MAX;
        for (digest, record) in &self.tickets {
            let wait = record.wait;
            if wait < best_wait || (wait == best_wait && (best.is_empty() || digest < &best)) {
                best = digest.clone();
                best_wait = wait;
            }
        }
        if best.is_empty() {
            (String::new(), 0)
        } else {
            (best, best_wait)
        }
    }

    fn canonical_proof_hex(text: &str) -> Option<String> {
        let proof = vdf::hex_to_proof(text).ok()?;
        let canonical = vdf::proof_to_hex(&proof);
        if canonical == text {
            Some(text.to_owned())
        } else {
            None
        }
    }

    fn parse(&self, message: &JsonValue) -> Option<(String, Stored)> {
        let obj = message.as_object()?;
        if obj.get("consensus").and_then(JsonValue::as_str) != Some("poet") {
            return None;
        }
        let wait_raw = obj.get("wait").and_then(JsonValue::as_i64)?;
        if !(1..=4_294_967_295).contains(&wait_raw) {
            return None;
        }
        let wait = wait_raw as u32;
        let author = obj.get("author").and_then(JsonValue::as_str)?;
        let payload = obj.get("payload").and_then(JsonValue::as_str)?;
        let proof = obj.get("proof").and_then(JsonValue::as_str)?;
        if author.is_empty() || payload.is_empty() {
            return None;
        }
        let proof_hex = Self::canonical_proof_hex(proof)?;
        let proof_int = vdf::hex_to_proof(&proof_hex).ok()?;
        if !vdf::verify(&self.seed_bytes, wait, &proof_int) {
            return None;
        }
        let digest = ticket_id(author, payload, &proof_hex, wait).ok()?;
        if self.tickets.contains_key(&digest) {
            return None;
        }
        Some((digest, Stored { wait }))
    }
}

pub fn ticket_id(author: &str, payload: &str, proof: &str, wait: u32) -> Result<String, String> {
    let payload = JsonValue::object([
        ("author".into(), JsonValue::String(author.to_owned())),
        ("payload".into(), JsonValue::String(payload.to_owned())),
        ("proof".into(), JsonValue::String(proof.to_owned())),
        ("wait".into(), JsonValue::Number(wait as i64)),
    ]);
    merkle_digest(&payload).map_err(|e| e.to_string())
}

impl ApplicationObject for ProofOfElapsedTime {
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
            self.tickets.insert(digest.clone(), record);
            self.order.push(digest);
        }
        Some(self.emit_state_memento())
    }

    fn emit_state_memento(&self) -> StateMemento {
        let (winner, wait) = self.winner();
        let payload = JsonValue::object([
            ("v".into(), JsonValue::Number(1)),
            ("wait".into(), JsonValue::Number(wait as i64)),
            ("winner".into(), JsonValue::String(winner)),
        ]);
        let digest = merkle_digest(&payload).expect("canonical");
        StateMemento::normalize(&digest, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        let (winner, _) = self.winner();
        if winner.is_empty() {
            Vec::new()
        } else {
            vec![winner]
        }
    }

    fn is_merkelized(&self) -> bool {
        true
    }
}
