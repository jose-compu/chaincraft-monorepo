//! Transaction pool — SPEC/features/mempool-basic.md.

use std::collections::HashMap;

use indexmap::IndexMap;

use crate::canonical::JsonValue;
use crate::object::merkle_digest;

pub const DEFAULT_CAPACITY: usize = 8;
pub const DEFAULT_MIN_FEE: i64 = 0;
pub const DEFAULT_TTL_MS: i64 = 60_000;
pub const DEFAULT_MAX_PER_SENDER: usize = 0;
pub const DEFAULT_RBF_MIN_INCREASE: i64 = 1;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InsertResult {
    pub accepted: bool,
    pub evicted: String,
    pub expired: usize,
    pub replaced: String,
}

#[derive(Clone, Debug)]
struct Entry {
    fee: i64,
    nonce: i64,
    received_at: i64,
    sender: String,
}

pub fn transaction_id(fee: i64, nonce: i64, payload: &str, sender: &str) -> String {
    merkle_digest(&JsonValue::object([
        ("fee".into(), JsonValue::Number(fee)),
        ("nonce".into(), JsonValue::Number(nonce)),
        ("payload".into(), JsonValue::String(payload.to_owned())),
        ("sender".into(), JsonValue::String(sender.to_owned())),
    ]))
    .expect("canonical")
}

fn parse_tx(message: &JsonValue) -> Option<(String, String, i64, i64, String)> {
    let obj = message.as_object()?;
    let sender = obj.get("sender").and_then(JsonValue::as_str)?;
    let payload = obj.get("payload").and_then(JsonValue::as_str)?;
    let fee = obj.get("fee").and_then(JsonValue::as_i64)?;
    let nonce = obj.get("nonce").and_then(JsonValue::as_i64)?;
    if sender.is_empty() || payload.is_empty() || fee < 0 || nonce < 0 {
        return None;
    }
    Some((
        transaction_id(fee, nonce, payload, sender),
        sender.to_owned(),
        fee,
        nonce,
        payload.to_owned(),
    ))
}

#[derive(Debug)]
pub struct Mempool {
    capacity: usize,
    min_fee: i64,
    ttl_ms: i64,
    max_per_sender: usize,
    rbf_min_increase: i64,
    entries: IndexMap<String, Entry>,
    slots: HashMap<(String, i64), String>,
}

impl Mempool {
    pub fn new(
        capacity: usize,
        min_fee: i64,
        ttl_ms: i64,
        max_per_sender: usize,
        rbf_min_increase: i64,
    ) -> Result<Self, String> {
        if capacity < 1 {
            return Err("capacity must be >= 1".into());
        }
        if min_fee < 0 {
            return Err("min_fee must be >= 0".into());
        }
        if ttl_ms < 0 {
            return Err("ttl_ms must be >= 0".into());
        }
        if rbf_min_increase < 1 {
            return Err("rbf_min_increase must be >= 1".into());
        }
        Ok(Self {
            capacity,
            min_fee,
            ttl_ms,
            max_per_sender,
            rbf_min_increase,
            entries: IndexMap::new(),
            slots: HashMap::new(),
        })
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn ids(&self) -> Vec<String> {
        self.entries.keys().cloned().collect()
    }

    pub fn insert(&mut self, message: &JsonValue, now_ms: i64) -> InsertResult {
        let expired = self.sweep(now_ms);
        let Some((txid, sender, fee, nonce, _payload)) = parse_tx(message) else {
            return Self::result(false, "", "", expired);
        };
        if self.entries.contains_key(&txid) {
            return Self::result(false, "", "", expired);
        }
        if fee < self.min_fee {
            return Self::result(false, "", "", expired);
        }
        let mut replaced = String::new();
        let slot = (sender.clone(), nonce);
        if let Some(existing_id) = self.slots.get(&slot).cloned() {
            let existing_fee = self.entries.get(&existing_id).map(|e| e.fee).unwrap_or(0);
            if fee < existing_fee + self.rbf_min_increase {
                return Self::result(false, "", "", expired);
            }
            self.discard(&existing_id);
            replaced = existing_id;
        }
        if replaced.is_empty()
            && self.max_per_sender > 0
            && self.sender_count(&sender) >= self.max_per_sender
        {
            return Self::result(false, "", "", expired);
        }
        let mut evicted = String::new();
        if self.entries.len() >= self.capacity {
            match self.lowest_fee() {
                Some(victim) if self.entries[&victim].fee < fee => {
                    self.discard(&victim);
                    evicted = victim;
                }
                _ => return Self::result(false, &replaced, "", expired),
            }
        }
        self.entries.insert(
            txid.clone(),
            Entry {
                fee,
                nonce,
                received_at: now_ms,
                sender: sender.clone(),
            },
        );
        self.slots.insert(slot, txid);
        Self::result(true, &replaced, &evicted, expired)
    }

    pub fn remove(&mut self, txid: &str) -> bool {
        self.discard(txid)
    }

    pub fn sweep(&mut self, now_ms: i64) -> usize {
        if self.ttl_ms == 0 {
            return 0;
        }
        let expired: Vec<String> = self
            .entries
            .iter()
            .filter(|(_, entry)| now_ms - entry.received_at > self.ttl_ms)
            .map(|(id, _)| id.clone())
            .collect();
        for id in &expired {
            self.discard(id);
        }
        expired.len()
    }

    fn result(accepted: bool, replaced: &str, evicted: &str, expired: usize) -> InsertResult {
        InsertResult {
            accepted,
            evicted: evicted.to_owned(),
            expired,
            replaced: replaced.to_owned(),
        }
    }

    fn discard(&mut self, txid: &str) -> bool {
        let Some(entry) = self.entries.shift_remove(txid) else {
            return false;
        };
        self.slots.remove(&(entry.sender, entry.nonce));
        true
    }

    fn sender_count(&self, sender: &str) -> usize {
        self.entries.values().filter(|e| e.sender == sender).count()
    }

    fn lowest_fee(&self) -> Option<String> {
        let mut best: Option<(&str, i64)> = None;
        for (id, entry) in &self.entries {
            match best {
                Some((_, fee)) if entry.fee >= fee => {}
                _ => best = Some((id.as_str(), entry.fee)),
            }
        }
        best.map(|(id, _)| id.to_owned())
    }
}
