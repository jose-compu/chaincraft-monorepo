//! Chained VRF randomness beacon — SPEC/features/consensus-beacon.md.

use std::any::Any;
use std::collections::HashMap;

use crate::canonical::{canonical_json, JsonValue, MAX_SAFE_INT};
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};
use crate::vrf;

pub const GENESIS_PREVIOUS: &str =
    "0000000000000000000000000000000000000000000000000000000000000000";

#[derive(Clone, Debug)]
struct Stored {
    height: i64,
    output: String,
}

#[derive(Debug, Default)]
pub struct RandomnessBeacon {
    pulses: HashMap<String, Stored>,
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
    let bytes = hex::decode(text).ok()?;
    if bytes.len() != nbytes {
        return None;
    }
    Some(text.to_owned())
}

pub fn pulse_id(
    height: i64,
    output: &str,
    pk: &str,
    previous: &str,
    proof: &str,
) -> Result<String, String> {
    let payload = JsonValue::object([
        ("height".into(), JsonValue::Number(height)),
        ("output".into(), JsonValue::String(output.to_owned())),
        ("pk".into(), JsonValue::String(pk.to_owned())),
        ("previous".into(), JsonValue::String(previous.to_owned())),
        ("proof".into(), JsonValue::String(proof.to_owned())),
    ]);
    merkle_digest(&payload).map_err(|e| e.to_string())
}

impl RandomnessBeacon {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn state(&self) -> (Vec<String>, i64, String) {
        let pulses = self.order.clone();
        let (height, output) = self.tip();
        (pulses.clone(), height, output)
    }

    fn tip(&self) -> (i64, String) {
        if self.order.is_empty() {
            return (-1, String::new());
        }
        let record = &self.pulses[self.order.last().expect("tip")];
        (record.height, record.output.clone())
    }

    fn parse(&self, message: &JsonValue) -> Option<(String, Stored)> {
        let obj = message.as_object()?;
        if obj.get("consensus").and_then(JsonValue::as_str) != Some("beacon") {
            return None;
        }
        let height = is_int(obj.get("height")?)?;
        let previous = hex_lower(obj.get("previous").and_then(JsonValue::as_str)?, 32)?;
        let pk = hex_lower(obj.get("pk").and_then(JsonValue::as_str)?, 33)?;
        let proof = hex_lower(obj.get("proof").and_then(JsonValue::as_str)?, 64)?;
        let output_hex = hex_lower(obj.get("output").and_then(JsonValue::as_str)?, 32)?;
        let (tip_height, tip_output) = self.tip();
        if tip_height < 0 {
            if height != 0 || previous != GENESIS_PREVIOUS {
                return None;
            }
        } else if height != tip_height + 1 || previous != tip_output {
            return None;
        }
        let vrf_message = canonical_json(&JsonValue::object([
            ("height".into(), JsonValue::Number(height)),
            ("previous".into(), JsonValue::String(previous.clone())),
        ]))
        .ok()?;
        let proof_bytes = hex::decode(&proof).ok()?;
        let pk_bytes = hex::decode(&pk).ok()?;
        let output_bytes = hex::decode(&output_hex).ok()?;
        if !vrf::verify(
            vrf_message.as_bytes(),
            &proof_bytes,
            &pk_bytes,
            Some(output_bytes.as_slice()),
        ) {
            return None;
        }
        let digest = pulse_id(height, &output_hex, &pk, &previous, &proof).ok()?;
        if self.pulses.contains_key(&digest) {
            return None;
        }
        Some((
            digest,
            Stored {
                height,
                output: output_hex,
            },
        ))
    }
}

impl ApplicationObject for RandomnessBeacon {
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
            self.pulses.insert(digest.clone(), record);
            self.order.push(digest);
        }
        Some(self.emit_state_memento())
    }

    fn emit_state_memento(&self) -> StateMemento {
        let (height, output) = self.tip();
        let payload = JsonValue::object([
            ("height".into(), JsonValue::Number(height)),
            ("output".into(), JsonValue::String(output)),
            ("v".into(), JsonValue::Number(1)),
        ]);
        let digest = merkle_digest(&payload).expect("canonical");
        StateMemento::normalize(&digest, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        if self.order.is_empty() {
            Vec::new()
        } else {
            vec![self.order.last().expect("tip").clone()]
        }
    }

    fn is_merkelized(&self) -> bool {
        true
    }
}
