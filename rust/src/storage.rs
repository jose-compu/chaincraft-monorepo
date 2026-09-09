//! Persistent message store — SPEC/features/storage-persistent.md.

use indexmap::IndexMap;

use crate::canonical::JsonValue;

pub const DEFAULT_CAPACITY: usize = 8;

pub fn is_valid_id(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

#[derive(Debug)]
pub struct MessageStore {
    capacity: usize,
    entries: IndexMap<String, String>,
}

impl MessageStore {
    pub fn new(capacity: usize) -> Result<Self, String> {
        if capacity < 1 {
            return Err("capacity must be >= 1".into());
        }
        Ok(Self {
            capacity,
            entries: IndexMap::new(),
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

    pub fn put(&mut self, record_id: &str, body: &str) -> bool {
        if !is_valid_id(record_id) || body.is_empty() {
            return false;
        }
        if self.entries.contains_key(record_id) {
            self.entries.insert(record_id.to_owned(), body.to_owned());
            return false;
        }
        if self.entries.len() >= self.capacity {
            if let Some(oldest) = self.entries.keys().next().cloned() {
                self.entries.shift_remove(&oldest);
            }
        }
        self.entries.insert(record_id.to_owned(), body.to_owned());
        true
    }

    pub fn get(&self, record_id: &str) -> (bool, String) {
        match self.entries.get(record_id) {
            Some(body) => (true, body.clone()),
            None => (false, String::new()),
        }
    }

    pub fn remove(&mut self, record_id: &str) -> bool {
        self.entries.shift_remove(record_id).is_some()
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
        true
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
