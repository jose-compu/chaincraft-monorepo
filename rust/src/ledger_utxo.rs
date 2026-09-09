//! UTXO ledger — SPEC/features/ledger-utxo.md.

use std::any::Any;
use std::collections::{BTreeMap, HashMap, HashSet};

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
    for (owner, value) in allocations {
        if owner.is_empty() || *value < 1 || *value > MAX_SAFE_INT {
            return Err("each allocation must be an integer in 1..2^53-1".into());
        }
        out.insert(owner.clone(), *value);
    }
    Ok(out)
}

type ParsedTx = (i64, Vec<String>, Vec<(String, i64)>, String);

pub fn transaction_id(fee: i64, inputs: &[String], outputs: &[(String, i64)]) -> String {
    merkle_digest(&JsonValue::object([
        ("fee".into(), JsonValue::Number(fee)),
        (
            "inputs".into(),
            JsonValue::Array(inputs.iter().cloned().map(JsonValue::String).collect()),
        ),
        (
            "outputs".into(),
            JsonValue::Array(
                outputs
                    .iter()
                    .map(|(owner, value)| {
                        JsonValue::object([
                            ("owner".into(), JsonValue::String(owner.clone())),
                            ("value".into(), JsonValue::Number(*value)),
                        ])
                    })
                    .collect(),
            ),
        ),
    ]))
    .expect("canonical")
}

#[derive(Clone, Debug)]
struct Stored {
    owner: String,
    value: i64,
}

#[derive(Debug)]
pub struct UtxoLedger {
    utxos: HashMap<String, Stored>,
    order: Vec<String>,
    burned: i64,
}

impl UtxoLedger {
    pub fn new(allocations: BTreeMap<String, i64>) -> Result<Self, String> {
        let genesis = normalize_allocations(&allocations)?;
        let mut utxos = HashMap::new();
        let mut order = Vec::new();
        for (owner, value) in genesis {
            let id = format!("genesis:{owner}");
            utxos.insert(id.clone(), Stored { owner, value });
            order.push(id);
        }
        Ok(Self {
            utxos,
            order,
            burned: 0,
        })
    }

    pub fn default_set() -> Self {
        Self::new(default_allocations()).expect("defaults")
    }

    pub fn state(&self) -> (i64, i64, Vec<(String, String, i64)>) {
        let entries = self.entries();
        let supply = entries.iter().map(|(_, _, value)| value).sum();
        (self.burned, supply, entries)
    }

    fn entries(&self) -> Vec<(String, String, i64)> {
        self.order
            .iter()
            .map(|id| {
                let stored = &self.utxos[id];
                (id.clone(), stored.owner.clone(), stored.value)
            })
            .collect()
    }

    fn snapshot_object(&self) -> JsonValue {
        JsonValue::object([
            ("burned".into(), JsonValue::Number(self.burned)),
            (
                "utxos".into(),
                JsonValue::Array(
                    self.entries()
                        .into_iter()
                        .map(|(id, owner, value)| {
                            JsonValue::object([
                                ("id".into(), JsonValue::String(id)),
                                ("owner".into(), JsonValue::String(owner)),
                                ("value".into(), JsonValue::Number(value)),
                            ])
                        })
                        .collect(),
                ),
            ),
            ("v".into(), JsonValue::Number(1)),
        ])
    }

    fn parse(&self, message: &JsonValue) -> Option<ParsedTx> {
        let obj = message.as_object()?;
        if obj.get("ledger").and_then(JsonValue::as_str) != Some("utxo") {
            return None;
        }
        let fee = obj.get("fee").and_then(JsonValue::as_i64)?;
        if fee < 0 {
            return None;
        }
        let raw_inputs = obj.get("inputs").and_then(JsonValue::as_array)?;
        if raw_inputs.is_empty() {
            return None;
        }
        let mut inputs = Vec::new();
        let mut seen = HashSet::new();
        let mut incoming = 0;
        for item in raw_inputs {
            let id = item.as_str()?;
            if id.is_empty() || !seen.insert(id.to_owned()) {
                return None;
            }
            let stored = self.utxos.get(id)?;
            incoming += stored.value;
            inputs.push(id.to_owned());
        }
        let raw_outputs = obj.get("outputs").and_then(JsonValue::as_array)?;
        let mut outputs = Vec::new();
        let mut outgoing = 0;
        for item in raw_outputs {
            let output = item.as_object()?;
            let owner = output.get("owner").and_then(JsonValue::as_str)?;
            let value = output.get("value").and_then(JsonValue::as_i64)?;
            if owner.is_empty() || value < 1 {
                return None;
            }
            outgoing += value;
            outputs.push((owner.to_owned(), value));
        }
        if incoming != outgoing + fee {
            return None;
        }
        let txid = transaction_id(fee, &inputs, &outputs);
        Some((fee, inputs, outputs, txid))
    }
}

impl ApplicationObject for UtxoLedger {
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
        if let Some((fee, inputs, outputs, txid)) = self.parse(message) {
            for id in &inputs {
                self.utxos.remove(id);
                self.order.retain(|item| item != id);
            }
            for (index, (owner, value)) in outputs.into_iter().enumerate() {
                let out_id = format!("{txid}:{index}");
                self.utxos.insert(out_id.clone(), Stored { owner, value });
                self.order.push(out_id);
            }
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
