//! PeerJS ids, broker options, and an in-memory cross-scheme relay.
//!
//! SPEC/features/channel-peer.md. Signaling is an HTTP GET, which this crate
//! does not perform. `parse_peer_id_body` checks the response text. The relay
//! does not open an ICE data channel.

use std::collections::{BTreeMap, BTreeSet};

use crate::canonical::JsonValue;
use crate::channel::{self, is_peer_id};
use crate::envelope::Envelope;
use crate::error::Error;

pub const DEFAULT_PEER_ORIGIN: &str = "https://dechess-org-peerjs.vercel.app";
pub const PEER_KEY: &str = "peerjs";

const RELAY: &[&str] = &["udp", "mailto", "webrtc", "forum", "pipe"];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PeerOptions {
    pub host: String,
    pub port: u16,
    pub path: String,
    pub secure: bool,
    pub key: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RelayItem {
    pub id: String,
    pub type_name: String,
    pub from: String,
}

pub fn parse_peer_id_body(text: &str) -> Option<String> {
    let ident = text.trim();
    if !is_peer_id(ident) {
        return None;
    }
    Some(ident.to_owned())
}

pub fn peer_options(origin: &str) -> Result<PeerOptions, Error> {
    let (secure, rest) = if let Some(rest) = origin.strip_prefix("https://") {
        (true, rest)
    } else if let Some(rest) = origin.strip_prefix("http://") {
        (false, rest)
    } else {
        return Err(Error::protocol("peer origin must be http or https"));
    };
    let hostport = rest.split('/').next().unwrap_or("");
    if hostport.is_empty() {
        return Err(Error::protocol("peer origin must be http or https"));
    }
    let (host, port) = match hostport.rsplit_once(':') {
        Some((host, port))
            if !host.is_empty() && !port.is_empty() && port.bytes().all(|b| b.is_ascii_digit()) =>
        {
            let port: u16 = port
                .parse()
                .map_err(|_| Error::protocol("peer origin must be http or https"))?;
            (host.to_owned(), port)
        }
        _ => (hostport.to_owned(), if secure { 443 } else { 80 }),
    };
    Ok(PeerOptions {
        host,
        port,
        path: "/".to_owned(),
        secure,
        key: PEER_KEY.to_owned(),
    })
}

pub struct EnvelopeRelay {
    order: Vec<String>,
    inbox: BTreeMap<String, Vec<RelayItem>>,
    seen: BTreeSet<String>,
}

impl EnvelopeRelay {
    pub fn new() -> Self {
        Self {
            order: Vec::new(),
            inbox: BTreeMap::new(),
            seen: BTreeSet::new(),
        }
    }

    pub fn join(&mut self, addr: &str) -> bool {
        let parsed = channel::parse_address(addr);
        if !parsed.ok || !RELAY.contains(&parsed.scheme.as_str()) {
            return false;
        }
        if self.inbox.contains_key(&parsed.canonical) {
            return false;
        }
        self.order.push(parsed.canonical.clone());
        self.inbox.insert(parsed.canonical, Vec::new());
        true
    }

    pub fn publish(&mut self, src: &str, type_name: &str, data: JsonValue) -> Option<String> {
        let parsed = channel::parse_address(src);
        if !parsed.ok || !self.inbox.contains_key(&parsed.canonical) {
            return None;
        }
        let env = Envelope::build(type_name, data, Some(0)).ok()?;
        if !self.seen.insert(env.id.clone()) {
            return Some(env.id);
        }
        let item = RelayItem {
            id: env.id.clone(),
            type_name: env.type_name.clone(),
            from: parsed.canonical.clone(),
        };
        for member in &self.order {
            if member == &parsed.canonical {
                continue;
            }
            if let Some(box_) = self.inbox.get_mut(member) {
                box_.push(item.clone());
            }
        }
        Some(env.id)
    }

    pub fn take(&mut self, addr: &str) -> Vec<RelayItem> {
        let parsed = channel::parse_address(addr);
        if !parsed.ok {
            return Vec::new();
        }
        match self.inbox.get_mut(&parsed.canonical) {
            Some(box_) => std::mem::take(box_),
            None => Vec::new(),
        }
    }
}

impl Default for EnvelopeRelay {
    fn default() -> Self {
        Self::new()
    }
}
