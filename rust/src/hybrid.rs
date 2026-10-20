//! One mesh, one channel per peer — SPEC/features/channel-hybrid.md.

use std::collections::{BTreeMap, BTreeSet};

use crate::canonical::JsonValue;
use crate::channel::parse_address;
use crate::envelope::Envelope;

pub fn hop_cap(scheme: &str) -> Option<usize> {
    match scheme {
        "tcp" => Some(262_144),
        "udp" | "webrtc" | "pipe" => Some(65_507),
        "mailto" | "forum" => Some(4096),
        "loop" => Some(64),
        _ => None,
    }
}

pub fn hello_caps(udp: bool) -> Vec<&'static str> {
    if udp {
        vec!["digest-sync", "gossip", "udp"]
    } else {
        vec!["digest-sync", "gossip"]
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HybridItem {
    pub id: String,
    pub type_name: String,
    pub from: String,
}

pub struct LinkMesh {
    order: Vec<String>,
    scheme: BTreeMap<String, String>,
    inbox: BTreeMap<String, Vec<HybridItem>>,
    seen: BTreeSet<String>,
}

impl LinkMesh {
    pub fn new() -> Self {
        Self {
            order: Vec::new(),
            scheme: BTreeMap::new(),
            inbox: BTreeMap::new(),
            seen: BTreeSet::new(),
        }
    }

    pub fn join(&mut self, addr: &str) -> bool {
        let parsed = parse_address(addr);
        if !parsed.ok || hop_cap(&parsed.scheme).is_none() {
            return false;
        }
        if self.inbox.contains_key(&parsed.canonical) {
            return false;
        }
        self.order.push(parsed.canonical.clone());
        self.scheme.insert(parsed.canonical.clone(), parsed.scheme);
        self.inbox.insert(parsed.canonical, Vec::new());
        true
    }

    pub fn gossip(&mut self, src: &str, type_name: &str, data: JsonValue) -> Option<String> {
        self.send(src, None, type_name, data, true)
    }

    pub fn direct(
        &mut self,
        src: &str,
        dst: &str,
        type_name: &str,
        data: JsonValue,
    ) -> Option<String> {
        self.send(src, Some(dst), type_name, data, false)
    }

    pub fn take(&mut self, addr: &str) -> Vec<HybridItem> {
        let Some(canonical) = canonical_of(addr) else {
            return Vec::new();
        };
        match self.inbox.get_mut(&canonical) {
            Some(box_) => std::mem::take(box_),
            None => Vec::new(),
        }
    }

    fn send(
        &mut self,
        src: &str,
        dst: Option<&str>,
        type_name: &str,
        data: JsonValue,
        gossip: bool,
    ) -> Option<String> {
        let source = canonical_of(src)?;
        if !self.inbox.contains_key(&source) {
            return None;
        }
        let target = if gossip {
            None
        } else {
            let canonical = canonical_of(dst?)?;
            if !self.inbox.contains_key(&canonical) {
                return None;
            }
            Some(canonical)
        };
        let env = Envelope::build(type_name, data, Some(0)).ok()?;
        if gossip && env.is_control() {
            return None;
        }
        if !gossip && !env.is_control() {
            return None;
        }
        if !self.seen.insert(env.id.clone()) {
            return Some(env.id);
        }
        let size = env.to_bytes().ok()?.len();
        let item = HybridItem {
            id: env.id.clone(),
            type_name: env.type_name.clone(),
            from: source.clone(),
        };
        if gossip {
            let order = self.order.clone();
            for member in order {
                if member == source {
                    continue;
                }
                let scheme = self.scheme.get(&member).map(String::as_str).unwrap_or("");
                if size <= hop_cap(scheme).unwrap_or(0) {
                    if let Some(box_) = self.inbox.get_mut(&member) {
                        box_.push(item.clone());
                    }
                }
            }
        } else if let Some(target) = target {
            let scheme = self.scheme.get(&target).map(String::as_str).unwrap_or("");
            if size <= hop_cap(scheme).unwrap_or(0) {
                if let Some(box_) = self.inbox.get_mut(&target) {
                    box_.push(item);
                }
            }
        }
        Some(env.id)
    }
}

impl Default for LinkMesh {
    fn default() -> Self {
        Self::new()
    }
}

fn canonical_of(addr: &str) -> Option<String> {
    let parsed = parse_address(addr);
    if parsed.ok {
        Some(parsed.canonical)
    } else {
        None
    }
}
