//! Persistent message store — SPEC/features/storage-persistent.md, storage-index.md.

use std::collections::{HashMap, HashSet};

use indexmap::IndexMap;

use crate::canonical::{JsonValue, MAX_SAFE_INT, MIN_SAFE_INT};
use crate::envelope::Envelope;

pub const DEFAULT_CAPACITY: usize = 8;
const MAX_REGISTRATIONS: usize = 8;

pub fn is_valid_id(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

fn is_type(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes.iter().all(|b| {
            b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'.' | b'_' | b'-')
        })
}

fn is_field(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes.iter().all(|b| {
            b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-')
        })
}

type RegKey = (String, String);
type IndexKey = (String, String, String);

fn is_wire_int(value: &JsonValue) -> bool {
    value
        .as_i64()
        .is_some_and(|n| (MIN_SAFE_INT..=MAX_SAFE_INT).contains(&n))
}

fn encode_value(value: &JsonValue) -> Option<String> {
    match value {
        JsonValue::String(s) => Some(format!("s:{s}")),
        JsonValue::Bool(b) => Some(format!("b:{}", if *b { 1 } else { 0 })),
        JsonValue::Number(n) if is_wire_int(value) => Some(format!("i:{n}")),
        _ => None,
    }
}

fn decode_query_value(value: &JsonValue) -> Option<String> {
    encode_value(value)
}

fn index_values(raw: &JsonValue) -> Vec<JsonValue> {
    match raw {
        JsonValue::String(_) | JsonValue::Bool(_) => vec![raw.clone()],
        JsonValue::Number(_) if is_wire_int(raw) => vec![raw.clone()],
        JsonValue::Array(items) => {
            let mut out = Vec::new();
            let mut seen = HashSet::new();
            for item in items {
                let Some(enc) = encode_value(item) else {
                    continue;
                };
                if seen.insert(enc) {
                    out.push(item.clone());
                }
            }
            out
        }
        _ => Vec::new(),
    }
}

#[derive(Debug)]
pub struct MessageStore {
    capacity: usize,
    entries: IndexMap<String, String>,
    registrations: HashSet<RegKey>,
    postings: HashMap<IndexKey, Vec<String>>,
    id_keys: HashMap<String, HashSet<IndexKey>>,
}

impl MessageStore {
    pub fn new(capacity: usize) -> Result<Self, String> {
        if capacity < 1 {
            return Err("capacity must be >= 1".into());
        }
        Ok(Self {
            capacity,
            entries: IndexMap::new(),
            registrations: HashSet::new(),
            postings: HashMap::new(),
            id_keys: HashMap::new(),
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

    pub fn register(&mut self, type_: &str, field: &str) -> bool {
        if !is_type(type_) || !is_field(field) {
            return false;
        }
        let key = (type_.to_owned(), field.to_owned());
        if self.registrations.contains(&key) {
            return true;
        }
        if self.registrations.len() >= MAX_REGISTRATIONS {
            return false;
        }
        self.registrations.insert(key);
        true
    }

    pub fn query(&self, type_: &str, field: &str, value: &JsonValue) -> Vec<String> {
        let Some(enc) = decode_query_value(value) else {
            return Vec::new();
        };
        if !self.registrations.contains(&(type_.to_owned(), field.to_owned())) {
            return Vec::new();
        }
        let key = (type_.to_owned(), field.to_owned(), enc);
        self.postings.get(&key).cloned().unwrap_or_default()
    }

    pub fn put(&mut self, record_id: &str, body: &str) -> bool {
        if !is_valid_id(record_id) || body.is_empty() {
            return false;
        }
        if self.entries.contains_key(record_id) {
            self.unindex_id(record_id);
            self.entries.insert(record_id.to_owned(), body.to_owned());
            self.index_body(record_id, body);
            return false;
        }
        if self.entries.len() >= self.capacity {
            if let Some(oldest) = self.entries.keys().next().cloned() {
                self.unindex_id(&oldest);
                self.entries.shift_remove(&oldest);
            }
        }
        self.entries.insert(record_id.to_owned(), body.to_owned());
        self.index_body(record_id, body);
        true
    }

    pub fn get(&self, record_id: &str) -> (bool, String) {
        match self.entries.get(record_id) {
            Some(body) => (true, body.clone()),
            None => (false, String::new()),
        }
    }

    pub fn remove(&mut self, record_id: &str) -> bool {
        if self.entries.shift_remove(record_id).is_none() {
            return false;
        }
        self.unindex_id(record_id);
        true
    }

    pub fn dump(&self) -> (Vec<(String, String)>, i64) {
        (
            self.entries
                .iter()
                .map(|(id, body)| (body.clone(), id.clone()))
                .collect(),
            1,
        )
    }

    pub fn load(&mut self, snapshot: &JsonValue) -> bool {
        let Some(parsed) = parse_snapshot(snapshot, self.capacity) else {
            return false;
        };
        self.entries = parsed;
        self.rebuild_index();
        true
    }

    fn rebuild_index(&mut self) {
        self.postings.clear();
        self.id_keys.clear();
        let items: Vec<(String, String)> = self
            .entries
            .iter()
            .map(|(id, body)| (id.clone(), body.clone()))
            .collect();
        for (id, body) in items {
            self.index_body(&id, &body);
        }
    }

    fn unindex_id(&mut self, record_id: &str) {
        let Some(keys) = self.id_keys.remove(record_id) else {
            return;
        };
        for key in keys {
            if let Some(bucket) = self.postings.get_mut(&key) {
                bucket.retain(|id| id != record_id);
                if bucket.is_empty() {
                    self.postings.remove(&key);
                }
            }
        }
    }

    fn index_body(&mut self, record_id: &str, body: &str) {
        let Ok(env) = Envelope::parse_text(body, None) else {
            return;
        };
        let JsonValue::Object(data) = &env.data else {
            return;
        };
        let mut keys_for_id = HashSet::new();
        for (type_, field) in &self.registrations {
            if env.type_name != *type_ {
                continue;
            }
            let Some(raw) = data.get(field) else {
                continue;
            };
            for value in index_values(raw) {
                let Some(enc) = encode_value(&value) else {
                    continue;
                };
                let idx = (type_.clone(), field.clone(), enc);
                keys_for_id.insert(idx.clone());
                let bucket = self.postings.entry(idx).or_default();
                if !bucket.contains(&record_id.to_owned()) {
                    bucket.push(record_id.to_owned());
                }
            }
        }
        if !keys_for_id.is_empty() {
            self.id_keys.insert(record_id.to_owned(), keys_for_id);
        }
    }
}

fn parse_snapshot(snapshot: &JsonValue, capacity: usize) -> Option<IndexMap<String, String>> {
    let obj = snapshot.as_object()?;
    if obj.get("v").and_then(JsonValue::as_i64) != Some(1) {
        return None;
    }
    let raw = obj.get("entries").and_then(JsonValue::as_array)?;
    if raw.len() > capacity {
        return None;
    }
    let mut out = IndexMap::new();
    for item in raw {
        let entry = item.as_object()?;
        let id = entry.get("id").and_then(JsonValue::as_str)?;
        let body = entry.get("body").and_then(JsonValue::as_str)?;
        if !is_valid_id(id) || body.is_empty() || out.contains_key(id) {
            return None;
        }
        out.insert(id.to_owned(), body.to_owned());
    }
    Some(out)
}