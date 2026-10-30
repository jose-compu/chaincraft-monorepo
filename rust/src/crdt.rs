//! Last-write-wins key-value CRDT — SPEC/features/protocol-crdt-kv.md.

use std::collections::BTreeMap;

use crate::canonical::{JsonValue, MAX_SAFE_INT};
use crate::object::Protocol;

pub const MAX_KEYS: usize = 32;
pub const MAX_VALUE: usize = 256;

struct Register {
    ts: i64,
    writer: String,
    value: String,
    deleted: bool,
}

pub struct CrdtKv {
    keys: BTreeMap<String, Register>,
}

impl CrdtKv {
    pub fn new() -> Self {
        Self {
            keys: BTreeMap::new(),
        }
    }

    pub fn state_value(&self) -> JsonValue {
        JsonValue::object([("keys".into(), JsonValue::Array(self.key_list()))])
    }

    fn key_list(&self) -> Vec<JsonValue> {
        self.keys
            .iter()
            .map(|(key, item)| {
                JsonValue::object([
                    ("deleted".into(), JsonValue::Bool(item.deleted)),
                    ("key".into(), JsonValue::String(key.clone())),
                    ("ts".into(), JsonValue::Number(item.ts)),
                    ("value".into(), JsonValue::String(item.value.clone())),
                    ("writer".into(), JsonValue::String(item.writer.clone())),
                ])
            })
            .collect()
    }

    fn parse(&self, message: &JsonValue) -> Option<Op> {
        let obj = message.as_object()?;
        if obj.get("app").and_then(JsonValue::as_str) != Some("crdt") {
            return None;
        }
        let op = obj.get("op").and_then(JsonValue::as_str)?;
        let key = obj.get("key").and_then(JsonValue::as_str)?;
        let writer = obj.get("writer").and_then(JsonValue::as_str)?;
        let ts = obj.get("ts").and_then(JsonValue::as_i64)?;
        if !matches!(op, "set" | "del") || !valid_name(key) || !valid_name(writer) {
            return None;
        }
        if !(0..=MAX_SAFE_INT).contains(&ts) {
            return None;
        }
        let deleted = op == "del";
        let value = if deleted {
            String::new()
        } else {
            let text = obj.get("value").and_then(JsonValue::as_str)?;
            let scalars = text.chars().count();
            if !(1..=MAX_VALUE).contains(&scalars) {
                return None;
            }
            text.to_owned()
        };
        match self.keys.get(key) {
            None if self.keys.len() >= MAX_KEYS => None,
            Some(current) if current.ts == ts && current.writer == writer => {
                if current.deleted != deleted || current.value != value {
                    None
                } else {
                    Some(Op {
                        key: key.to_owned(),
                        ts,
                        writer: writer.to_owned(),
                        value,
                        deleted,
                    })
                }
            }
            _ => Some(Op {
                key: key.to_owned(),
                ts,
                writer: writer.to_owned(),
                value,
                deleted,
            }),
        }
    }
}

impl Default for CrdtKv {
    fn default() -> Self {
        Self::new()
    }
}

struct Op {
    key: String,
    ts: i64,
    writer: String,
    value: String,
    deleted: bool,
}

fn valid_name(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
}

impl Protocol for CrdtKv {
    fn accept(&self, message: &JsonValue) -> bool {
        self.parse(message).is_some()
    }

    fn receive(&mut self, message: &JsonValue) {
        let Some(op) = self.parse(message) else {
            return;
        };
        match self.keys.get(&op.key) {
            None => {
                self.keys.insert(
                    op.key,
                    Register {
                        ts: op.ts,
                        writer: op.writer,
                        value: op.value,
                        deleted: op.deleted,
                    },
                );
            }
            Some(current) if op.ts == current.ts && op.writer == current.writer => {}
            Some(current)
                if op.ts > current.ts || (op.ts == current.ts && op.writer < current.writer) =>
            {
                self.keys.insert(
                    op.key,
                    Register {
                        ts: op.ts,
                        writer: op.writer,
                        value: op.value,
                        deleted: op.deleted,
                    },
                );
            }
            Some(_) => {}
        }
    }
}
