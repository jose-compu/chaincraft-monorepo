//! Node JSON-lines command surface — SPEC/features/cli-node.md.

use crate::canonical::{parse_json, payload_digest, JsonValue};
use crate::channel::parse_address;

fn type_ok(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value
            .bytes()
            .all(|b| matches!(b, b'a'..=b'z' | b'0'..=b'9' | b'.' | b'_' | b'-'))
}

fn error_event(message: &str) -> JsonValue {
    JsonValue::object([
        ("event".into(), JsonValue::String("error".into())),
        ("message".into(), JsonValue::String(message.to_owned())),
    ])
}

#[derive(Debug)]
pub struct NodeSession {
    impl_name: String,
    listen: String,
    peers: Vec<String>,
    ids: Vec<String>,
    closed: bool,
}

impl NodeSession {
    pub fn new(impl_name: &str, listen: &str) -> Result<Self, String> {
        if impl_name.is_empty() || listen.is_empty() {
            return Err("impl and listen must be non-empty".into());
        }
        Ok(Self {
            impl_name: impl_name.to_owned(),
            listen: listen.to_owned(),
            peers: Vec::new(),
            ids: Vec::new(),
            closed: false,
        })
    }

    pub fn start(&self) -> Vec<JsonValue> {
        vec![JsonValue::object([
            ("event".into(), JsonValue::String("ready".into())),
            ("addr".into(), JsonValue::String(self.listen.clone())),
            ("impl".into(), JsonValue::String(self.impl_name.clone())),
        ])]
    }

    pub fn handle(&mut self, line: &str) -> Vec<JsonValue> {
        if line.trim().is_empty() {
            return Vec::new();
        }
        if self.closed {
            return vec![error_event("closed")];
        }
        let command = match parse_json(line) {
            Ok(value) => value,
            Err(_) => return vec![error_event("invalid json")],
        };
        let Some(obj) = command.as_object() else {
            return vec![error_event("invalid json")];
        };
        match obj.get("cmd").and_then(JsonValue::as_str) {
            Some("connect") => self.connect(obj),
            Some("send") => self.send(obj),
            Some("ids") => vec![JsonValue::object([
                ("event".into(), JsonValue::String("ids".into())),
                (
                    "ids".into(),
                    JsonValue::Array(self.ids.iter().cloned().map(JsonValue::String).collect()),
                ),
            ])],
            Some("quit") => {
                self.closed = true;
                vec![JsonValue::object([(
                    "event".into(),
                    JsonValue::String("quit".into()),
                )])]
            }
            _ => vec![error_event("unknown cmd")],
        }
    }

    pub fn state(&self) -> (bool, Vec<String>, Vec<String>) {
        (self.closed, self.ids.clone(), self.peers.clone())
    }

    fn connect(
        &mut self,
        command: &std::collections::BTreeMap<String, JsonValue>,
    ) -> Vec<JsonValue> {
        let Some(addr) = command.get("addr").and_then(JsonValue::as_str) else {
            return vec![error_event("invalid address")];
        };
        if !parse_address(addr).ok {
            return vec![error_event("invalid address")];
        }
        if !self.peers.iter().any(|item| item == addr) {
            self.peers.push(addr.to_owned());
        }
        vec![JsonValue::object([
            ("event".into(), JsonValue::String("connected".into())),
            ("addr".into(), JsonValue::String(addr.to_owned())),
        ])]
    }

    fn send(&mut self, command: &std::collections::BTreeMap<String, JsonValue>) -> Vec<JsonValue> {
        let Some(type_name) = command.get("type").and_then(JsonValue::as_str) else {
            return vec![error_event("invalid send")];
        };
        if !type_ok(type_name) {
            return vec![error_event("invalid send")];
        }
        let Some(data) = command.get("data") else {
            return vec![error_event("invalid send")];
        };
        let Ok(digest) = payload_digest(data) else {
            return vec![error_event("invalid send")];
        };
        self.ids.push(digest.clone());
        vec![JsonValue::object([
            ("event".into(), JsonValue::String("sent".into())),
            ("id".into(), JsonValue::String(digest)),
        ])]
    }
}
