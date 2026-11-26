//! Ouroboros slot-leader object — SPEC/features/consensus-ouroboros.md.

use std::any::Any;
use std::collections::{HashMap, HashSet};

use num_bigint::BigUint;

use crate::canonical::{canonical_json, JsonValue, MAX_SAFE_INT};
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};
use crate::vrf;

fn is_nonce(nonce: &str) -> bool {
    nonce.len() == 64
        && nonce
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

#[derive(Clone, Debug)]
struct Stored {
    slot: i64,
    parent: String,
    output: String,
    epoch_nonce: String,
}

#[derive(Debug)]
struct Stakeholder {
    stake: i64,
    pk: String,
}

#[derive(Debug)]
pub struct Ouroboros {
    nonce: String,
    epoch_length: i64,
    stakeholders: HashMap<String, Stakeholder>,
    total_stake: i64,
    blocks: HashMap<String, Stored>,
    order: Vec<String>,
}

fn is_int(value: &JsonValue) -> Option<i64> {
    let n = value.as_i64()?;
    if !(0..=MAX_SAFE_INT).contains(&n) {
        return None;
    }
    Some(n)
}

fn hex_lower(text: &str, nbytes: usize) -> Option<String> {
    if text.len() != nbytes * 2 {
        return None;
    }
    if text != text.to_lowercase() {
        return None;
    }
    hex::decode(text).ok()?;
    Some(text.to_owned())
}

pub fn epoch_of(slot: i64, epoch_length: i64) -> i64 {
    (slot - 1) / epoch_length
}

pub fn eligible(output: &[u8], stake: i64, total: i64) -> bool {
    if total == stake {
        return true;
    }
    let o_val = BigUint::from_bytes_be(output);
    let scale = BigUint::from(1u32) << 256;
    let left = o_val * BigUint::from(total as u64);
    let right = BigUint::from(stake as u64) * scale;
    left < right
}

pub fn block_id(
    slot: i64,
    parent: &str,
    payload: &str,
    leader: &str,
    pk: &str,
    proof: &str,
    output: &str,
) -> Result<String, String> {
    let payload = JsonValue::object([
        ("leader".into(), JsonValue::String(leader.to_owned())),
        ("output".into(), JsonValue::String(output.to_owned())),
        ("parent".into(), JsonValue::String(parent.to_owned())),
        ("payload".into(), JsonValue::String(payload.to_owned())),
        ("pk".into(), JsonValue::String(pk.to_owned())),
        ("proof".into(), JsonValue::String(proof.to_owned())),
        ("slot".into(), JsonValue::Number(slot)),
    ]);
    merkle_digest(&payload).map_err(|e| e.to_string())
}

impl Ouroboros {
    pub fn new(
        nonce: &str,
        epoch_length: i64,
        stakeholders: &[(String, i64, String)],
    ) -> Result<Self, String> {
        if !is_nonce(nonce) {
            return Err("nonce must be 64 lowercase hex characters".into());
        }
        if !(1..=MAX_SAFE_INT).contains(&epoch_length) {
            return Err("epoch_length must be an integer >= 1".into());
        }
        if stakeholders.is_empty() {
            return Err("stakeholders must be non-empty".into());
        }
        let mut seen = HashSet::new();
        let mut table = HashMap::new();
        let mut total = 0i64;
        for (sid, stake, pk_hex) in stakeholders {
            if sid.is_empty() {
                return Err("each stakeholder id must be a non-empty string".into());
            }
            if *stake < 1 || *stake > MAX_SAFE_INT {
                return Err("each stake must be an integer >= 1".into());
            }
            if hex_lower(pk_hex, 33).is_none() {
                return Err("each pk must be 66 lowercase hex characters".into());
            }
            if !seen.insert(sid.clone()) {
                return Err("stakeholder ids must be distinct".into());
            }
            total = total
                .checked_add(*stake)
                .ok_or_else(|| "stake sum exceeds safe integer range".to_string())?;
            table.insert(
                sid.clone(),
                Stakeholder {
                    stake: *stake,
                    pk: pk_hex.clone(),
                },
            );
        }
        Ok(Self {
            nonce: nonce.to_owned(),
            epoch_length,
            stakeholders: table,
            total_stake: total,
            blocks: HashMap::new(),
            order: Vec::new(),
        })
    }

    pub fn state(&self) -> (i64, String, Vec<String>, Vec<String>, i64, String) {
        let (tip_slot, tip) = self.tip();
        let canonical = self.canonical(&tip);
        let (epoch, nonce) = self.next_slot_context(tip_slot, &tip);
        (tip_slot, tip, canonical, self.order.clone(), epoch, nonce)
    }

    fn tip(&self) -> (i64, String) {
        let mut best = String::new();
        let mut best_slot = 0;
        for (digest, record) in &self.blocks {
            if record.slot > best_slot
                || (record.slot == best_slot && (best.is_empty() || digest < &best))
            {
                best = digest.clone();
                best_slot = record.slot;
            }
        }
        (best_slot, best)
    }

    fn canonical(&self, tip: &str) -> Vec<String> {
        let mut chain = Vec::new();
        let mut cursor = tip.to_owned();
        while !cursor.is_empty() {
            chain.push(cursor.clone());
            cursor = self.blocks[&cursor].parent.clone();
        }
        chain.reverse();
        chain
    }

    fn next_slot_context(&self, tip_slot: i64, tip: &str) -> (i64, String) {
        if tip_slot == 0 {
            return (epoch_of(1, self.epoch_length), self.nonce.clone());
        }
        let next_slot = tip_slot + 1;
        self.epoch_nonce_for_slot(next_slot, self.blocks.get(tip))
    }

    fn epoch_nonce_for_slot(&self, slot: i64, parent: Option<&Stored>) -> (i64, String) {
        let epoch = epoch_of(slot, self.epoch_length);
        let pos = (slot - 1).rem_euclid(self.epoch_length);
        if epoch == 0 {
            return (epoch, self.nonce.clone());
        }
        if pos == 0 {
            let parent = parent.expect("parent required for epoch boundary");
            return (epoch, parent.output.clone());
        }
        let parent = parent.expect("parent required");
        (epoch, parent.epoch_nonce.clone())
    }

    fn vrf_message(&self, epoch: i64, nonce: &str, slot: i64, leader: &str) -> Option<Vec<u8>> {
        let payload = JsonValue::object([
            ("epoch".into(), JsonValue::Number(epoch)),
            ("nonce".into(), JsonValue::String(nonce.to_owned())),
            ("slot".into(), JsonValue::Number(slot)),
            ("stakeholder".into(), JsonValue::String(leader.to_owned())),
        ]);
        let text = canonical_json(&payload).ok()?;
        Some(text.into_bytes())
    }

    fn parse(&self, message: &JsonValue) -> Option<(String, Stored)> {
        let obj = message.as_object()?;
        if obj.get("consensus").and_then(JsonValue::as_str) != Some("ouroboros") {
            return None;
        }
        let slot = is_int(obj.get("slot")?)?;
        if slot < 1 {
            return None;
        }
        let leader = obj.get("leader").and_then(JsonValue::as_str)?;
        let parent = obj.get("parent").and_then(JsonValue::as_str)?;
        let payload = obj.get("payload").and_then(JsonValue::as_str)?;
        if leader.is_empty() || payload.is_empty() {
            return None;
        }
        let pk = hex_lower(obj.get("pk").and_then(JsonValue::as_str)?, 33)?;
        let proof = hex_lower(obj.get("proof").and_then(JsonValue::as_str)?, 64)?;
        let output_hex = hex_lower(obj.get("output").and_then(JsonValue::as_str)?, 32)?;
        let holder = self.stakeholders.get(leader)?;
        if holder.pk != pk {
            return None;
        }
        let parent_record = if parent.is_empty() {
            if slot != 1 {
                return None;
            }
            None
        } else {
            let record = self.blocks.get(parent)?;
            if record.slot != slot - 1 {
                return None;
            }
            Some(record)
        };
        let (epoch, epoch_nonce) = self.epoch_nonce_for_slot(slot, parent_record);
        let vrf_msg = self.vrf_message(epoch, &epoch_nonce, slot, leader)?;
        let proof_bytes = hex::decode(&proof).ok()?;
        let pk_bytes = hex::decode(&pk).ok()?;
        let output_bytes = hex::decode(&output_hex).ok()?;
        if !vrf::verify(&vrf_msg, &proof_bytes, &pk_bytes, Some(&output_bytes)) {
            return None;
        }
        if !eligible(&output_bytes, holder.stake, self.total_stake) {
            return None;
        }
        let digest = block_id(slot, parent, payload, leader, &pk, &proof, &output_hex).ok()?;
        if self.blocks.contains_key(&digest) {
            return None;
        }
        let pos = (slot - 1).rem_euclid(self.epoch_length);
        let stored_nonce = match (epoch, pos) {
            (0, _) => self.nonce.clone(),
            (_, 0) => parent_record.map(|p| p.output.clone())?,
            (_, _) => parent_record.map(|p| p.epoch_nonce.clone())?,
        };
        Some((
            digest,
            Stored {
                slot,
                parent: parent.to_owned(),
                output: output_hex,
                epoch_nonce: stored_nonce,
            },
        ))
    }
}

impl ApplicationObject for Ouroboros {
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
        let (tip_slot, tip) = self.tip();
        let (_, nonce) = self.next_slot_context(tip_slot, &tip);
        let payload = JsonValue::object([
            ("nonce".into(), JsonValue::String(nonce)),
            ("slot".into(), JsonValue::Number(tip_slot)),
            ("tip".into(), JsonValue::String(tip)),
            ("v".into(), JsonValue::Number(1)),
        ]);
        let digest = merkle_digest(&payload).expect("canonical");
        StateMemento::normalize(&digest, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        let (_, tip) = self.tip();
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
