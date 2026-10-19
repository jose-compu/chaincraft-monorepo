//! Peer address book and local-discovery policy.
//!
//! SPEC/features/discovery-peer.md and SPEC/features/discovery-local.md.

use std::collections::HashSet;

use indexmap::IndexMap;

pub const DEFAULT_CAPACITY: usize = 50;
pub const DEFAULT_TIMEOUT_MS: i64 = 120_000;

pub fn is_resolved_ip_allowed(ip: &str) -> bool {
    let labels: Vec<&str> = ip.split('.').collect();
    if labels.len() != 4
        || !labels
            .iter()
            .all(|label| label.bytes().all(|b| b.is_ascii_digit()))
    {
        return false;
    }
    let mut octets = [0u32; 4];
    for (i, label) in labels.iter().enumerate() {
        let Ok(value) = label.parse::<u32>() else {
            return false;
        };
        if value > 255 {
            return false;
        }
        octets[i] = value;
    }
    let a = octets[0];
    let b = octets[1];
    if a == 0 || a >= 224 {
        return false;
    }
    if a == 169 && b == 254 {
        return false;
    }
    true
}

pub fn is_connect_allowed(address: &str) -> bool {
    if !is_valid_address(address) {
        return false;
    }
    let Some((host, _)) = split_host_port(address) else {
        return false;
    };
    let labels: Vec<&str> = host.split('.').collect();
    if labels.len() == 4
        && labels
            .iter()
            .all(|label| label.bytes().all(|b| b.is_ascii_digit()))
    {
        return is_resolved_ip_allowed(host);
    }
    true
}

pub fn is_valid_address(address: &str) -> bool {
    match split_host_port(address) {
        Some((host, port)) => valid_host(host) && valid_port(port),
        None => false,
    }
}

fn split_host_port(address: &str) -> Option<(&str, &str)> {
    let idx = address.rfind(':')?;
    if idx == 0 || idx + 1 == address.len() {
        return None;
    }
    Some((&address[..idx], &address[idx + 1..]))
}

fn valid_port(port: &str) -> bool {
    if port.is_empty() || !port.bytes().all(|b| b.is_ascii_digit()) {
        return false;
    }
    if port.len() > 1 && port.starts_with('0') {
        return false;
    }
    matches!(port.parse::<u32>(), Ok(value) if (1..=65535).contains(&value))
}

fn valid_host(host: &str) -> bool {
    if host.is_empty() || host.len() > 253 {
        return false;
    }
    let labels: Vec<&str> = host.split('.').collect();
    if labels.len() == 4
        && labels
            .iter()
            .all(|label| label.bytes().all(|b| b.is_ascii_digit()))
    {
        return valid_ipv4(&labels);
    }
    valid_hostname(&labels)
}

fn valid_ipv4(labels: &[&str]) -> bool {
    for label in labels {
        if label.len() > 1 && label.starts_with('0') {
            return false;
        }
        match label.parse::<u32>() {
            Ok(value) if value <= 255 => {}
            _ => return false,
        }
    }
    true
}

fn valid_hostname(labels: &[&str]) -> bool {
    if labels.is_empty() || labels[0].is_empty() || labels[labels.len() - 1].is_empty() {
        return false;
    }
    for label in labels {
        if label.is_empty() || label.len() > 63 {
            return false;
        }
        let bytes = label.as_bytes();
        if bytes[0] == b'-' || bytes[bytes.len() - 1] == b'-' {
            return false;
        }
        if !bytes
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || *b == b'-')
        {
            return false;
        }
    }
    true
}

#[derive(Debug)]
pub struct AddressBook {
    listen: Option<String>,
    capacity: usize,
    timeout_ms: i64,
    entries: IndexMap<String, i64>,
    solicited: HashSet<String>,
}

impl AddressBook {
    pub fn new(listen: Option<&str>, capacity: usize, timeout_ms: i64) -> Result<Self, String> {
        if capacity < 1 {
            return Err("capacity must be a positive integer".into());
        }
        if timeout_ms < 1 {
            return Err("timeout_ms must be a positive integer".into());
        }
        if let Some(addr) = listen {
            if !is_valid_address(addr) {
                return Err("listen must be a valid address or None".into());
            }
        }
        Ok(Self {
            listen: listen.map(str::to_owned),
            capacity,
            timeout_ms,
            entries: IndexMap::new(),
            solicited: HashSet::new(),
        })
    }

    pub fn contains(&self, address: &str) -> bool {
        self.entries.contains_key(address)
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn addresses(&self) -> Vec<String> {
        self.entries.keys().cloned().collect()
    }

    pub fn insert(&mut self, address: &str, now_ms: i64) -> bool {
        self.put(address, now_ms, true)
    }

    pub fn ingest(&mut self, addresses: &[String], now_ms: i64, solicited: bool) -> usize {
        if !solicited {
            return 0;
        }
        let mut added = 0;
        for address in addresses {
            if self.put(address, now_ms, false) {
                added += 1;
            }
        }
        added
    }

    pub fn advertise(&self) -> Vec<String> {
        let mut out = self.addresses();
        out.sort();
        out
    }

    pub fn sweep(&mut self, now_ms: i64) -> usize {
        let timeout = self.timeout_ms;
        let expired: Vec<String> = self
            .entries
            .iter()
            .filter(|(_, seen)| now_ms - **seen > timeout)
            .map(|(address, _)| address.clone())
            .collect();
        for address in &expired {
            self.entries.shift_remove(address);
            self.solicited.remove(address);
        }
        expired.len()
    }

    pub fn mark_solicited(&mut self, peer: &str) -> bool {
        if !is_valid_address(peer) {
            return false;
        }
        self.solicited.insert(peer.to_owned());
        true
    }

    pub fn is_solicited(&self, peer: &str) -> bool {
        self.solicited.contains(peer)
    }

    pub fn clear_solicited(&mut self, peer: &str) {
        self.solicited.remove(peer);
    }

    fn put(&mut self, address: &str, now_ms: i64, evict: bool) -> bool {
        if !is_valid_address(address) || self.listen.as_deref() == Some(address) {
            return false;
        }
        if self.entries.contains_key(address) {
            self.entries[address] = now_ms;
            return false;
        }
        if self.entries.len() >= self.capacity {
            if !evict {
                return false;
            }
            if let Some((oldest, _)) = self.entries.first() {
                let oldest = oldest.clone();
                self.entries.shift_remove(&oldest);
                self.solicited.remove(&oldest);
            }
        }
        self.entries.insert(address.to_owned(), now_ms);
        true
    }
}

#[derive(Debug)]
pub struct LocalDiscovery {
    enabled: bool,
}

impl LocalDiscovery {
    pub fn new(enabled: bool) -> Self {
        Self { enabled }
    }

    pub fn request(&self, book: &mut AddressBook, peer: &str) -> bool {
        if !self.enabled {
            return false;
        }
        book.mark_solicited(peer)
    }

    pub fn reply(&self, book: &AddressBook) -> Option<Vec<String>> {
        if !self.enabled {
            return None;
        }
        Some(book.advertise())
    }

    pub fn accept(
        &self,
        book: &mut AddressBook,
        from_peer: &str,
        addresses: &[String],
        now_ms: i64,
    ) -> usize {
        if !self.enabled || !book.is_solicited(from_peer) {
            return 0;
        }
        book.clear_solicited(from_peer);
        book.ingest(addresses, now_ms, true)
    }
}
