//! Pedagogical NAT traversal — SPEC/features/discovery-nat.md.

use serde_json::{json, Value};

use crate::discovery::is_valid_address;
use crate::error::{Error, Result};

pub const APP_NAT: &str = "app.nat";
pub const PUNCH_HEX: &str = "00";

const MAGIC: u32 = 0x2112_A442;
const MAGIC_B: [u8; 4] = [0x21, 0x12, 0xa4, 0x42];
const BINDING_REQUEST: u16 = 0x0001;
const BINDING_SUCCESS: u16 = 0x0101;
const XOR_MAPPED: u16 = 0x0020;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecResult {
    pub ok: bool,
    pub packet: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedBinding {
    pub ok: bool,
    pub host: String,
    pub port: u16,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Punch {
    pub ok: bool,
    pub datagram: String,
    pub addr: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RelayOut {
    pub ok: bool,
    pub message: Option<Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HandleOut {
    pub ok: bool,
    pub action: String,
    pub addr: String,
    pub reply: Option<Value>,
}

pub struct NatTraversal {
    listen: String,
    fixed: Option<String>,
    mapped: Option<String>,
    relay: Option<String>,
    armed: bool,
    opened: Vec<String>,
    seen: Vec<(String, String, String, String)>,
}

impl NatTraversal {
    pub fn new(listen: &str, external: Option<&str>, relay: Option<&str>) -> Result<Self> {
        if !is_valid_address(listen) {
            return Err(Error::protocol("invalid listen address"));
        }
        if let Some(addr) = external {
            if !is_valid_address(addr) {
                return Err(Error::protocol("invalid external address"));
            }
        }
        if let Some(addr) = relay {
            if !is_valid_address(addr) {
                return Err(Error::protocol("invalid relay address"));
            }
        }
        Ok(Self {
            listen: listen.to_owned(),
            fixed: external.map(str::to_owned),
            mapped: external.map(str::to_owned),
            relay: relay.map(str::to_owned),
            armed: false,
            opened: Vec::new(),
            seen: Vec::new(),
        })
    }

    pub fn armed(&self) -> bool {
        self.armed
    }

    pub fn arm(&mut self, transport: &str) -> bool {
        self.armed = transport == "udp";
        self.armed
    }

    pub fn external_address(&self) -> String {
        self.mapped.clone().unwrap_or_default()
    }

    pub fn advertise(&self) -> String {
        self.mapped.clone().unwrap_or_else(|| self.listen.clone())
    }

    pub fn observe_stun(&mut self, packet: &str, txid: &str) -> bool {
        if !self.armed || self.fixed.is_some() {
            return false;
        }
        let parsed = parse_binding_response(packet, txid);
        if !parsed.ok {
            return false;
        }
        let mapped = format!("{}:{}", parsed.host, parsed.port);
        if !is_valid_address(&mapped) {
            return false;
        }
        self.mapped = Some(mapped);
        true
    }

    pub fn punch(&self, peer: &str) -> Punch {
        if !self.armed || !is_valid_address(peer) || self.ours(peer) {
            return Punch {
                ok: false,
                datagram: String::new(),
                addr: String::new(),
            };
        }
        Punch {
            ok: true,
            datagram: PUNCH_HEX.to_owned(),
            addr: peer.to_owned(),
        }
    }

    pub fn observe_punch(&mut self, datagram: &str, origin: &str) -> bool {
        if !self.armed || datagram != PUNCH_HEX || !is_valid_address(origin) || self.ours(origin) {
            return false;
        }
        if !self.opened.iter().any(|item| item == origin) {
            self.opened.push(origin.to_owned());
        }
        true
    }

    pub fn opened(&self) -> Vec<String> {
        self.opened.clone()
    }

    pub fn relay_request(&self, target: &str) -> RelayOut {
        let Some(relay) = &self.relay else {
            return RelayOut {
                ok: false,
                message: None,
            };
        };
        if !self.armed
            || !is_valid_address(target)
            || self.ours(target)
            || target == relay
            || self.opened.iter().any(|item| item == target)
        {
            return RelayOut {
                ok: false,
                message: None,
            };
        }
        RelayOut {
            ok: true,
            message: Some(json!({
                "from": self.advertise(),
                "nat": "request",
                "relay": relay,
                "target": target,
            })),
        }
    }

    pub fn handle(&mut self, message: &Value) -> HandleOut {
        let fail = HandleOut {
            ok: false,
            action: String::new(),
            addr: String::new(),
            reply: None,
        };
        if !self.armed {
            return fail;
        }
        let Some(obj) = message.as_object() else {
            return fail;
        };
        let Some(kind) = obj.get("nat").and_then(Value::as_str) else {
            return fail;
        };
        if kind != "request" && kind != "response" {
            return fail;
        }
        let Some(origin) = obj.get("from").and_then(Value::as_str) else {
            return fail;
        };
        let Some(target) = obj.get("target").and_then(Value::as_str) else {
            return fail;
        };
        if !is_valid_address(origin) || !is_valid_address(target) || self.ours(origin) {
            return fail;
        }
        let relay = if kind == "request" {
            let Some(relay) = obj.get("relay").and_then(Value::as_str) else {
                return fail;
            };
            if !is_valid_address(relay) {
                return fail;
            }
            relay.to_owned()
        } else {
            String::new()
        };
        let ident = (
            kind.to_owned(),
            origin.to_owned(),
            target.to_owned(),
            relay.clone(),
        );
        if self.seen.iter().any(|item| item == &ident) {
            return fail;
        }
        if target == self.listen || target == self.advertise() {
            self.seen.push(ident);
            let reply = if kind == "request" {
                Some(json!({
                    "from": self.advertise(),
                    "nat": "response",
                    "target": origin,
                }))
            } else {
                if !self.opened.iter().any(|item| item == origin) {
                    self.opened.push(origin.to_owned());
                }
                None
            };
            return HandleOut {
                ok: true,
                action: "punch".to_owned(),
                addr: origin.to_owned(),
                reply,
            };
        }
        if kind == "request" && (relay == self.listen || relay == self.advertise()) {
            self.seen.push(ident);
            return HandleOut {
                ok: true,
                action: "forward".to_owned(),
                addr: target.to_owned(),
                reply: Some(json!({
                    "from": origin,
                    "nat": "request",
                    "relay": relay,
                    "target": target,
                })),
            };
        }
        fail
    }

    fn ours(&self, addr: &str) -> bool {
        addr == self.listen || addr == self.advertise()
    }
}

pub fn binding_request(txid: &str) -> CodecResult {
    let Some(raw) = txid_bytes(txid) else {
        return CodecResult {
            ok: false,
            packet: String::new(),
        };
    };
    CodecResult {
        ok: true,
        packet: to_hex(&header(BINDING_REQUEST, 0, &raw)),
    }
}

pub fn binding_success(txid: &str, host: &str, port: Option<i64>) -> CodecResult {
    let Some(raw) = txid_bytes(txid) else {
        return CodecResult {
            ok: false,
            packet: String::new(),
        };
    };
    let Some(octets) = ipv4(host) else {
        return CodecResult {
            ok: false,
            packet: String::new(),
        };
    };
    let Some(port) = port
        .and_then(|value| u16::try_from(value).ok())
        .filter(|value| *value >= 1)
    else {
        return CodecResult {
            ok: false,
            packet: String::new(),
        };
    };
    let value = xor_mapped(&octets, port);
    let mut attr = Vec::with_capacity(4 + value.len());
    attr.extend_from_slice(&XOR_MAPPED.to_be_bytes());
    attr.extend_from_slice(&(value.len() as u16).to_be_bytes());
    attr.extend_from_slice(&value);
    let mut packet = header(BINDING_SUCCESS, attr.len() as u16, &raw);
    packet.extend_from_slice(&attr);
    CodecResult {
        ok: true,
        packet: to_hex(&packet),
    }
}

pub fn parse_binding_response(packet: &str, txid: &str) -> ParsedBinding {
    let fail = ParsedBinding {
        ok: false,
        host: String::new(),
        port: 0,
    };
    let Some(raw) = unhex(packet) else {
        return fail;
    };
    let Some(ident) = txid_bytes(txid) else {
        return fail;
    };
    if raw.len() < 20 {
        return fail;
    }
    let msg_type = u16::from_be_bytes([raw[0], raw[1]]);
    let length = u16::from_be_bytes([raw[2], raw[3]]) as usize;
    let magic = u32::from_be_bytes([raw[4], raw[5], raw[6], raw[7]]);
    if msg_type != BINDING_SUCCESS || magic != MAGIC || raw[8..20] != ident[..] {
        return fail;
    }
    if length != raw.len() - 20 {
        return fail;
    }
    let end = 20 + length;
    let mut offset = 20;
    let mut found: Option<Vec<u8>> = None;
    while offset + 4 <= end {
        let atype = u16::from_be_bytes([raw[offset], raw[offset + 1]]);
        let alen = u16::from_be_bytes([raw[offset + 2], raw[offset + 3]]) as usize;
        offset += 4;
        if offset + alen > end {
            return fail;
        }
        let value = raw[offset..offset + alen].to_vec();
        offset += alen;
        let pad = (4 - (alen % 4)) % 4;
        if offset + pad > end {
            return fail;
        }
        offset += pad;
        if atype == XOR_MAPPED && found.is_none() {
            found = Some(value);
        }
    }
    let Some(found) = found else {
        return fail;
    };
    if offset != end || found.len() != 8 || found[0] != 0 || found[1] != 1 {
        return fail;
    }
    let xport = u16::from_be_bytes([found[2], found[3]]);
    let port = xport ^ 0x2112;
    if port == 0 {
        return fail;
    }
    let host = format!(
        "{}.{}.{}.{}",
        found[4] ^ MAGIC_B[0],
        found[5] ^ MAGIC_B[1],
        found[6] ^ MAGIC_B[2],
        found[7] ^ MAGIC_B[3]
    );
    ParsedBinding {
        ok: true,
        host,
        port,
    }
}

fn header(msg_type: u16, length: u16, txid: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(20);
    out.extend_from_slice(&msg_type.to_be_bytes());
    out.extend_from_slice(&length.to_be_bytes());
    out.extend_from_slice(&MAGIC.to_be_bytes());
    out.extend_from_slice(txid);
    out
}

fn xor_mapped(octets: &[u8; 4], port: u16) -> Vec<u8> {
    let xport = port ^ 0x2112;
    vec![
        0,
        1,
        (xport >> 8) as u8,
        (xport & 0xff) as u8,
        octets[0] ^ MAGIC_B[0],
        octets[1] ^ MAGIC_B[1],
        octets[2] ^ MAGIC_B[2],
        octets[3] ^ MAGIC_B[3],
    ]
}

fn txid_bytes(value: &str) -> Option<Vec<u8>> {
    let raw = unhex(value)?;
    if raw.len() == 12 {
        Some(raw)
    } else {
        None
    }
}

fn unhex(value: &str) -> Option<Vec<u8>> {
    if value.len() % 2 != 0 {
        return None;
    }
    let bytes = value.as_bytes();
    let mut out = Vec::with_capacity(value.len() / 2);
    let mut index = 0;
    while index < bytes.len() {
        let hi = hex_val(bytes[index])?;
        let lo = hex_val(bytes[index + 1])?;
        out.push((hi << 4) | lo);
        index += 2;
    }
    Some(out)
}

fn hex_val(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        _ => None,
    }
}

fn to_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

fn ipv4(host: &str) -> Option<[u8; 4]> {
    let mut octets = [0u8; 4];
    let mut count = 0;
    for label in host.split('.') {
        if count == 4 || label.is_empty() || !label.bytes().all(|byte| byte.is_ascii_digit()) {
            return None;
        }
        if label.len() > 1 && label.starts_with('0') {
            return None;
        }
        let value: u16 = label.parse().ok()?;
        if value > 255 {
            return None;
        }
        octets[count] = value as u8;
        count += 1;
    }
    if count == 4 {
        Some(octets)
    } else {
        None
    }
}
