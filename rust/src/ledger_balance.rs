//! Account-balance ledger — SPEC/features/ledger-balance.md.

use std::any::Any;
use std::collections::BTreeMap;

use crate::canonical::{JsonValue, MAX_SAFE_INT};
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};

pub fn default_allocations() -> BTreeMap<String, i64> {
    let mut map = BTreeMap::new();
    map.insert("alice".into(), 100);
    map
}

fn normalize_allocations(
    allocations: &BTreeMap<String, i64>,
) -> Result<BTreeMap<String, i64>, String> {
    if allocations.is_empty() {
        return Err("allocations must not be empty".into());
    }
    let mut out = BTreeMap::new();
    for (account, amount) in allocations {
        if account.is_empty() || *amount < 1 || *amount > MAX_SAFE_INT {
            return Err("each allocation must be an integer in 1..2^53-1".into());
        }
        out.insert(account.clone(), *amount);
    }
    Ok(out)
}

#[derive(Debug)]
pub struct BalanceLedger {
    balances: BTreeMap<String, i64>,
    nonces: BTreeMap<String, i64>,
    burned: i64,
}

impl BalanceLedger {
    pub fn new(allocations: BTreeMap<String, i64>) -> Result<Self, String> {
        let balances = normalize_allocations(&allocations)?;
        let nonces = balances.keys().cloned().map(|id| (id, 0)).collect();
        Ok(Self {
            balances,
            nonces,
            burned: 0,
        })
    }

    pub fn default_set() -> Self {
        Self::new(default_allocations()).expect("defaults")
    }

    pub fn state(&self) -> (BTreeMap<String, i64>, i64, BTreeMap<String, i64>, i64) {
        (
            self.balances.clone(),
            self.burned,
            self.nonces.clone(),
            self.supply(),
        )
    }

    fn supply(&self) -> i64 {
        self.balances.values().sum()
    }

    fn snapshot_object(&self) -> JsonValue {
        JsonValue::object([
            (
                "balances".into(),
                JsonValue::object(
                    self.balances
                        .iter()
                        .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                ),
            ),
            ("burned".into(), JsonValue::Number(self.burned)),
            (
                "nonces".into(),
                JsonValue::object(
                    self.nonces
                        .iter()
                        .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                ),
            ),
            ("v".into(), JsonValue::Number(1)),
        ])
    }

    fn parse(&self, message: &JsonValue) -> Option<(String, String, i64, i64)> {
        let obj = message.as_object()?;
        if obj.get("ledger").and_then(JsonValue::as_str) != Some("balance") {
            return None;
        }
        let sender = obj.get("sender").and_then(JsonValue::as_str)?;
        let recipient = obj.get("recipient").and_then(JsonValue::as_str)?;
        let amount = obj.get("amount").and_then(JsonValue::as_i64)?;
        let fee = obj.get("fee").and_then(JsonValue::as_i64)?;
        let nonce = obj.get("nonce").and_then(JsonValue::as_i64)?;
        if sender.is_empty() || recipient.is_empty() || amount < 1 || fee < 0 || nonce < 0 {
            return None;
        }
        if nonce != *self.nonces.get(sender).unwrap_or(&0) {
            return None;
        }
        if *self.balances.get(sender).unwrap_or(&0) < amount + fee {
            return None;
        }
        if *self.balances.get(recipient).unwrap_or(&0) + amount > MAX_SAFE_INT {
            return None;
        }
        Some((sender.to_owned(), recipient.to_owned(), amount, fee))
    }
}

impl ApplicationObject for BalanceLedger {
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
        if let Some((sender, recipient, amount, fee)) = self.parse(message) {
            *self.balances.entry(sender.clone()).or_insert(0) -= amount + fee;
            *self.balances.entry(recipient.clone()).or_insert(0) += amount;
            self.nonces.entry(recipient).or_insert(0);
            *self.nonces.entry(sender).or_insert(0) += 1;
            self.burned += fee;
        }
        Some(self.emit_state_memento())
    }

    fn emit_state_memento(&self) -> StateMemento {
        let digest = merkle_digest(&self.snapshot_object()).expect("canonical");
        StateMemento::normalize(&digest, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        let digest = self.emit_state_memento().canonical_digest;
        if digest.is_empty() {
            Vec::new()
        } else {
            vec![digest]
        }
    }

    fn is_merkelized(&self) -> bool {
        true
    }
}
