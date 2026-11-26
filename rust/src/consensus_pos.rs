//! Proof-of-stake object — SPEC/features/consensus-pos.md.

use std::any::Any;
use std::collections::BTreeMap;

use num_bigint::BigUint;
use num_traits::Zero;

use crate::canonical::JsonValue;
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};

pub const DEFAULT_SEED: &str = "chaincraft-pos-v1";

pub fn default_validators() -> BTreeMap<String, i64> {
    let mut map = BTreeMap::new();
    map.insert("alice".into(), 2);
    map.insert("bob".into(), 1);
    map.insert("carol".into(), 1);
    map
}

pub fn proposer_for(slot: i64, seed: &str, validators: &BTreeMap<String, i64>) -> String {
    let total: i64 = validators.values().sum();
    let digest = merkle_digest(&JsonValue::object([
        ("seed".into(), JsonValue::String(seed.to_owned())),
        ("slot".into(), JsonValue::Number(slot)),
    ]))
    .expect("canonical");
    let n = BigUint::parse_bytes(digest.as_bytes(), 16).unwrap();
    let pick = n % BigUint::from(total as u64);
    let mut acc = BigUint::zero();
    for (id, stake) in validators {
        acc += BigUint::from(*stake as u64);
        if pick < acc {
            return id.clone();
        }
    }
    panic!("stake walk missed");
}

#[derive(Debug)]
pub struct ProofOfStake {
    seed: String,
    validators: BTreeMap<String, i64>,
    current: i64,
    last_proposer: String,
    head: String,
}

impl ProofOfStake {
    pub fn new(seed: &str, validators: BTreeMap<String, i64>) -> Result<Self, String> {
        if seed.is_empty() {
            return Err("seed must be a non-empty string".into());
        }
        if validators.is_empty() {
            return Err("validators must not be empty".into());
        }
        for (id, stake) in &validators {
            if id.is_empty() || *stake < 1 {
                return Err("each validator needs a non-empty id and positive stake".into());
            }
        }
        Ok(Self {
            seed: seed.to_owned(),
            validators,
            current: 0,
            last_proposer: String::new(),
            head: String::new(),
        })
    }

    pub fn default_set() -> Self {
        Self::new(DEFAULT_SEED, default_validators()).expect("defaults")
    }

    pub fn stake_seed(&self) -> &str {
        &self.seed
    }

    pub fn stake_validators(&self) -> &BTreeMap<String, i64> {
        &self.validators
    }

    pub fn state(&self) -> (String, String, i64) {
        (self.head.clone(), self.last_proposer.clone(), self.current)
    }

    fn parse(&self, message: &JsonValue) -> Option<(i64, String, String)> {
        let obj = message.as_object()?;
        if obj.get("consensus").and_then(JsonValue::as_str) != Some("pos") {
            return None;
        }
        let slot = obj.get("slot").and_then(JsonValue::as_i64)?;
        let proposer = obj.get("proposer").and_then(JsonValue::as_str)?;
        let payload = obj.get("payload").and_then(JsonValue::as_str)?;
        if slot != self.current + 1 || proposer.is_empty() || payload.is_empty() {
            return None;
        }
        if proposer != proposer_for(slot, &self.seed, &self.validators) {
            return None;
        }
        Some((slot, proposer.to_owned(), payload.to_owned()))
    }
}

impl ApplicationObject for ProofOfStake {
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
        if let Some((slot, proposer, payload)) = self.parse(message) {
            self.current = slot;
            self.last_proposer = proposer;
            self.head = merkle_digest(&JsonValue::object([
                ("payload".into(), JsonValue::String(payload)),
                ("slot".into(), JsonValue::Number(slot)),
                ("v".into(), JsonValue::Number(1)),
            ]))
            .expect("canonical");
        }
        Some(self.emit_state_memento())
    }

    fn emit_state_memento(&self) -> StateMemento {
        StateMemento::normalize(&self.head, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        if self.head.is_empty() {
            Vec::new()
        } else {
            vec![self.head.clone()]
        }
    }

    fn is_merkelized(&self) -> bool {
        true
    }
}
