//! Local peer strike list — SPEC/features/discovery-ban.md.

use std::collections::BTreeMap;
use std::collections::VecDeque;

use serde_json::{json, Value};

use crate::discovery::is_valid_address;

pub const DEFAULT_STRIKE_LIMIT: u32 = 3;
pub const DEFAULT_BAN_TTL_MS: u64 = 60_000;
pub const MAX_TRACKED: usize = 64;

#[derive(Clone, Debug)]
struct Entry {
    strikes: u32,
    banned_at: Option<u64>,
}

pub struct BanSet {
    strike_limit: u32,
    ban_ttl_ms: u64,
    order: VecDeque<String>,
    peers: BTreeMap<String, Entry>,
}

pub fn classify_inbound(
    type_name: &str,
    solicited: bool,
    duplicate: bool,
    address_ok: bool,
) -> Value {
    if type_name == "ctl.peers" && !solicited {
        return json!({"action":"ignore","reason":Value::Null});
    }
    if type_name.starts_with("ctl.") || type_name.starts_with("link.") {
        return json!({"action":"deliver","reason":Value::Null});
    }
    if !address_ok {
        return json!({"action":"drop","reason":"invalid_address"});
    }
    if duplicate {
        return json!({"action":"drop","reason":"digest_flood"});
    }
    json!({"action":"deliver","reason":Value::Null})
}

impl BanSet {
    pub fn new(strike_limit: u32, ban_ttl_ms: u64) -> Result<Self, String> {
        if strike_limit < 1 {
            return Err("strike_limit must be a positive integer".into());
        }
        if ban_ttl_ms < 1 {
            return Err("ban_ttl_ms must be a positive integer".into());
        }
        Ok(Self {
            strike_limit,
            ban_ttl_ms,
            order: VecDeque::new(),
            peers: BTreeMap::new(),
        })
    }

    fn expire_peer(&mut self, peer: &str, now_ms: u64) {
        if let Some(entry) = self.peers.get(peer) {
            if let Some(at) = entry.banned_at {
                if now_ms.saturating_sub(at) > self.ban_ttl_ms {
                    self.remove_peer(peer);
                }
            }
        }
    }

    fn expire_all(&mut self, now_ms: u64) {
        let expired: Vec<String> = self
            .peers
            .iter()
            .filter_map(|(peer, entry)| {
                entry
                    .banned_at
                    .filter(|&at| now_ms.saturating_sub(at) > self.ban_ttl_ms)
                    .map(|_| peer.clone())
            })
            .collect();
        for peer in expired {
            self.remove_peer(&peer);
        }
    }

    fn is_active_ban(&self, entry: &Entry, now_ms: u64) -> bool {
        entry
            .banned_at
            .map(|at| now_ms.saturating_sub(at) <= self.ban_ttl_ms)
            .unwrap_or(false)
    }

    fn remove_peer(&mut self, peer: &str) {
        self.peers.remove(peer);
        self.order.retain(|item| item != peer);
    }

    fn evict_if_needed(&mut self) -> bool {
        if self.order.len() < MAX_TRACKED {
            return true;
        }
        for peer in self.order.iter() {
            if let Some(entry) = self.peers.get(peer) {
                if entry.banned_at.is_none() {
                    let victim = peer.clone();
                    self.remove_peer(&victim);
                    return true;
                }
            }
        }
        false
    }

    fn ensure_peer(&mut self, peer: &str) -> Option<&mut Entry> {
        if self.peers.contains_key(peer) {
            return self.peers.get_mut(peer);
        }
        if !self.evict_if_needed() {
            return None;
        }
        self.order.push_back(peer.to_string());
        self.peers.insert(
            peer.to_string(),
            Entry {
                strikes: 0,
                banned_at: None,
            },
        );
        self.peers.get_mut(peer)
    }

    pub fn note(&mut self, peer: &str, reason: &str, now_ms: u64) -> &'static str {
        if !is_valid_address(peer) {
            return "ignored";
        }
        let valid = matches!(reason, "digest_flood" | "malformed" | "invalid_address");
        if !valid {
            return "ignored";
        }

        self.expire_all(now_ms);
        if let Some(entry) = self.peers.get(peer) {
            if self.is_active_ban(entry, now_ms) {
                return "banned";
            }
        }

        let strike_limit = self.strike_limit;
        if reason == "invalid_address" {
            let entry = match self.ensure_peer(peer) {
                Some(entry) => entry,
                None => return "ignored",
            };
            entry.strikes = strike_limit;
            entry.banned_at = Some(now_ms);
            return "banned";
        }

        let entry = match self.ensure_peer(peer) {
            Some(entry) => entry,
            None => return "ignored",
        };
        entry.strikes += 1;
        if entry.strikes >= strike_limit {
            entry.banned_at = Some(now_ms);
            "banned"
        } else {
            "strike"
        }
    }

    pub fn is_banned(&mut self, peer: &str, now_ms: u64) -> bool {
        self.expire_peer(peer, now_ms);
        self.peers
            .get(peer)
            .map(|entry| self.is_active_ban(entry, now_ms))
            .unwrap_or(false)
    }

    pub fn strikes(&self, peer: &str) -> u32 {
        self.peers.get(peer).map(|e| e.strikes).unwrap_or(0)
    }

    pub fn banned(&mut self, now_ms: u64) -> Vec<String> {
        self.expire_all(now_ms);
        let mut out: Vec<String> = self
            .peers
            .iter()
            .filter_map(|(peer, entry)| {
                if self.is_active_ban(entry, now_ms) {
                    Some(peer.clone())
                } else {
                    None
                }
            })
            .collect();
        out.sort();
        out
    }

    pub fn state(&mut self, now_ms: u64) -> Value {
        self.expire_all(now_ms);
        let mut tracked = Vec::new();
        for peer in &self.order {
            let Some(entry) = self.peers.get(peer) else {
                continue;
            };
            tracked.push(json!({
                "peer": peer,
                "strikes": entry.strikes,
                "banned_at": entry.banned_at,
            }));
        }
        json!({
            "tracked": tracked,
            "banned": self.banned(now_ms),
            "size": self.order.len(),
        })
    }
}
