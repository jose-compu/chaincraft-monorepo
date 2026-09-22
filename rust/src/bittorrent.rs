//! Prototype BitTorrent swarm — SPEC/features/bittorrent-swarm.md.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::Mutex;

use sha2::{Digest, Sha256};

use crate::canonical::{bytes_to_hex, hex_to_bytes, JsonValue};
use crate::object::{merkle_digest, ApplicationObject, Protocol};

pub const WIRE_TYPE: &str = "app.bittorrent";
pub const MAX_TORRENTS: usize = 8;
pub const MAX_PIECES: usize = 64;
pub const MAX_PIECE_BYTES: usize = 65536;
pub const MAX_NAME_LEN: usize = 64;
pub const MAX_PEER_ID_LEN: usize = 64;
pub const MAX_HAVE_PEERS: usize = 32;
pub const MAX_SEED_BYTES: usize = MAX_PIECES * MAX_PIECE_BYTES;

pub fn piece_hash(data: &[u8]) -> String {
    bytes_to_hex(&Sha256::digest(data))
}

pub fn info_hash(name: &str, pieces: &[String]) -> String {
    merkle_digest(&JsonValue::object([
        ("name".into(), JsonValue::String(name.to_owned())),
        (
            "pieces".into(),
            JsonValue::Array(pieces.iter().cloned().map(JsonValue::String).collect()),
        ),
    ]))
    .expect("info hash")
}

pub fn split_payload(name: &str, text: &str, piece_size: usize) -> Result<Split, String> {
    if name.is_empty() || text.is_empty() || piece_size < 1 {
        return Err("name and data must be non-empty; piece_size >= 1".into());
    }
    if name.len() > MAX_NAME_LEN || piece_size > MAX_PIECE_BYTES {
        return Err("name or piece_size exceeds the prototype limit".into());
    }
    let raw = text.as_bytes();
    if raw.len() > MAX_SEED_BYTES {
        return Err("payload exceeds the prototype limit".into());
    }
    if raw.len().div_ceil(piece_size) > MAX_PIECES {
        return Err("too many pieces".into());
    }
    let chunks: Vec<&[u8]> = raw.chunks(piece_size).collect();
    let pieces: Vec<String> = chunks.iter().map(|chunk| piece_hash(chunk)).collect();
    let payloads: Vec<String> = chunks.iter().map(|chunk| bytes_to_hex(chunk)).collect();
    Ok(Split {
        info_hash: info_hash(name, &pieces),
        length: raw.len(),
        payloads,
        pieces,
    })
}

pub struct Split {
    pub info_hash: String,
    pub length: usize,
    pub payloads: Vec<String>,
    pub pieces: Vec<String>,
}

fn hex64(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

fn hex_body(value: &str) -> bool {
    !value.is_empty()
        && value.len() % 2 == 0
        && value
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

struct Torrent {
    name: String,
    pieces: Vec<String>,
    data: BTreeMap<i64, String>,
    have: BTreeMap<String, BTreeSet<i64>>,
}

enum Parsed {
    Metainfo {
        name: String,
        pieces: Vec<String>,
        digest: String,
    },
    Have {
        digest: String,
        peer: String,
        index: i64,
    },
    Piece {
        digest: String,
        peer: String,
        index: i64,
        data: String,
    },
    Request,
}

#[derive(Default)]
pub struct Swarm {
    torrents: HashMap<String, Torrent>,
}

impl Swarm {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn state(&self) -> JsonValue {
        JsonValue::object([
            ("torrents".into(), self.snapshot()),
            ("v".into(), JsonValue::Number(1)),
        ])
    }

    pub fn assembled(&self, digest: &str) -> Option<String> {
        let torrent = self.torrents.get(digest)?;
        let mut raw = Vec::new();
        for index in 0..torrent.pieces.len() as i64 {
            let hex = torrent.data.get(&index)?;
            raw.extend(hex_to_bytes(hex).ok()?);
        }
        Some(bytes_to_hex(&raw))
    }

    pub fn missing(&self, digest: &str) -> Vec<i64> {
        let Some(torrent) = self.torrents.get(digest) else {
            return Vec::new();
        };
        (0..torrent.pieces.len() as i64)
            .filter(|index| !torrent.data.contains_key(index))
            .collect()
    }

    pub fn piece_hex(&self, digest: &str, index: i64) -> Option<String> {
        self.torrents
            .get(digest)
            .and_then(|torrent| torrent.data.get(&index).cloned())
    }

    pub fn known(&self) -> Vec<String> {
        let mut ids: Vec<String> = self.torrents.keys().cloned().collect();
        ids.sort();
        ids
    }

    fn mark(torrent: &mut Torrent, peer: &str, index: i64) {
        torrent
            .have
            .entry(peer.to_owned())
            .or_default()
            .insert(index);
    }

    fn snapshot(&self) -> JsonValue {
        let mut torrents = BTreeMap::new();
        for (digest, torrent) in &self.torrents {
            let count = torrent.pieces.len() as i64;
            let mut have = BTreeMap::new();
            let mut complete = Vec::new();
            for (peer, indices) in &torrent.have {
                let list: Vec<i64> = indices.iter().copied().collect();
                if list.len() as i64 == count
                    && list.iter().enumerate().all(|(i, v)| *v == i as i64)
                {
                    complete.push(JsonValue::String(peer.clone()));
                }
                have.insert(
                    peer.clone(),
                    JsonValue::Array(list.into_iter().map(JsonValue::Number).collect()),
                );
            }
            let data = JsonValue::object(
                torrent
                    .data
                    .iter()
                    .map(|(index, hex)| (index.to_string(), JsonValue::String(hex.clone()))),
            );
            torrents.insert(
                digest.clone(),
                JsonValue::object([
                    ("complete".into(), JsonValue::Array(complete)),
                    ("data".into(), data),
                    ("have".into(), JsonValue::Object(have)),
                    ("name".into(), JsonValue::String(torrent.name.clone())),
                    (
                        "pieces".into(),
                        JsonValue::Array(
                            torrent
                                .pieces
                                .iter()
                                .cloned()
                                .map(JsonValue::String)
                                .collect(),
                        ),
                    ),
                ]),
            );
        }
        JsonValue::Object(torrents)
    }

    fn parse(&self, message: &JsonValue) -> Option<Parsed> {
        let obj = message.as_object()?;
        match obj.get("bt").and_then(JsonValue::as_str)? {
            "metainfo" => {
                let name = obj.get("name").and_then(JsonValue::as_str)?;
                let pieces = obj.get("pieces").and_then(JsonValue::as_array)?;
                if name.is_empty()
                    || name.len() > MAX_NAME_LEN
                    || pieces.is_empty()
                    || pieces.len() > MAX_PIECES
                {
                    return None;
                }
                let list: Vec<String> = pieces
                    .iter()
                    .map(|item| item.as_str().filter(|s| hex64(s)).map(str::to_owned))
                    .collect::<Option<Vec<_>>>()?;
                let digest = info_hash(name, &list);
                if let Some(existing) = self.torrents.get(&digest) {
                    if existing.name != name || existing.pieces != list {
                        return None;
                    }
                } else if self.torrents.len() >= MAX_TORRENTS {
                    return None;
                }
                Some(Parsed::Metainfo {
                    name: name.to_owned(),
                    pieces: list,
                    digest,
                })
            }
            kind @ ("have" | "piece" | "request") => {
                let digest = obj.get("info_hash").and_then(JsonValue::as_str)?;
                let peer = obj.get("peer").and_then(JsonValue::as_str)?;
                let index = obj.get("index").and_then(JsonValue::as_i64)?;
                if !hex64(digest) || peer.is_empty() || peer.len() > MAX_PEER_ID_LEN {
                    return None;
                }
                let torrent = self.torrents.get(digest)?;
                if index < 0 || index >= torrent.pieces.len() as i64 {
                    return None;
                }
                if kind != "request"
                    && !torrent.have.contains_key(peer)
                    && torrent.have.len() >= MAX_HAVE_PEERS
                {
                    return None;
                }
                if kind != "piece" {
                    return Some(if kind == "have" {
                        Parsed::Have {
                            digest: digest.to_owned(),
                            peer: peer.to_owned(),
                            index,
                        }
                    } else {
                        Parsed::Request
                    });
                }
                let data = obj.get("data").and_then(JsonValue::as_str)?;
                if data.len() > MAX_PIECE_BYTES * 2 || !hex_body(data) {
                    return None;
                }
                let raw = hex_to_bytes(data).ok()?;
                if piece_hash(&raw) != torrent.pieces[index as usize] {
                    return None;
                }
                Some(Parsed::Piece {
                    digest: digest.to_owned(),
                    peer: peer.to_owned(),
                    index,
                    data: data.to_owned(),
                })
            }
            _ => None,
        }
    }
}

impl Protocol for Swarm {
    fn accept(&self, message: &JsonValue) -> bool {
        self.parse(message).is_some()
    }

    fn receive(&mut self, message: &JsonValue) {
        if let Some(parsed) = self.parse(message) {
            match parsed {
                Parsed::Metainfo {
                    name,
                    pieces,
                    digest,
                } => {
                    self.torrents.entry(digest).or_insert_with(|| Torrent {
                        name,
                        pieces,
                        data: BTreeMap::new(),
                        have: BTreeMap::new(),
                    });
                }
                Parsed::Have {
                    digest,
                    peer,
                    index,
                } => {
                    if let Some(torrent) = self.torrents.get_mut(&digest) {
                        Self::mark(torrent, &peer, index);
                    }
                }
                Parsed::Piece {
                    digest,
                    peer,
                    index,
                    data,
                } => {
                    if let Some(torrent) = self.torrents.get_mut(&digest) {
                        torrent.data.insert(index, data);
                        Self::mark(torrent, &peer, index);
                    }
                }
                Parsed::Request => {}
            }
        }
    }
}

pub struct Client {
    swarm: Mutex<Swarm>,
    local_peer: Mutex<String>,
}

impl Default for Client {
    fn default() -> Self {
        Self::new()
    }
}

impl Client {
    pub fn new() -> Self {
        Self {
            swarm: Mutex::new(Swarm::new()),
            local_peer: Mutex::new(String::new()),
        }
    }

    pub fn on_app(&self, type_name: &str, data: &JsonValue) -> Option<JsonValue> {
        if type_name != WIRE_TYPE {
            return None;
        }
        {
            let mut swarm = self.swarm.lock().ok()?;
            if swarm.is_valid(data) {
                swarm.add_message(data, None);
            }
        }
        self.serve_request(data)
    }

    pub fn seed(
        &self,
        peer: &str,
        name: &str,
        data: &str,
        piece_size: usize,
    ) -> Result<(Vec<JsonValue>, String, usize, usize), String> {
        if peer.len() > MAX_PEER_ID_LEN || name.len() > MAX_NAME_LEN {
            return Err("peer or name exceeds the prototype limit".into());
        }
        *self.local_peer.lock().map_err(|e| e.to_string())? = peer.to_owned();
        let split = split_payload(name, data, piece_size)?;
        let mut messages = vec![JsonValue::object([
            ("bt".into(), JsonValue::String("metainfo".into())),
            ("name".into(), JsonValue::String(name.to_owned())),
            (
                "pieces".into(),
                JsonValue::Array(
                    split
                        .pieces
                        .iter()
                        .cloned()
                        .map(JsonValue::String)
                        .collect(),
                ),
            ),
        ])];
        for (index, piece) in split.payloads.iter().enumerate() {
            messages.push(JsonValue::object([
                ("bt".into(), JsonValue::String("piece".into())),
                ("data".into(), JsonValue::String(piece.clone())),
                ("index".into(), JsonValue::Number(index as i64)),
                (
                    "info_hash".into(),
                    JsonValue::String(split.info_hash.clone()),
                ),
                ("peer".into(), JsonValue::String(peer.to_owned())),
            ]));
        }
        Ok((messages, split.info_hash, split.length, split.pieces.len()))
    }

    pub fn leech(
        &self,
        peer: &str,
        info_hash_value: Option<&str>,
    ) -> Result<(Vec<JsonValue>, String, Vec<i64>), String> {
        if peer.len() > MAX_PEER_ID_LEN {
            return Err("peer exceeds the prototype limit".into());
        }
        *self.local_peer.lock().map_err(|e| e.to_string())? = peer.to_owned();
        let swarm = self.swarm.lock().map_err(|e| e.to_string())?;
        let digest = info_hash_value
            .map(str::to_owned)
            .unwrap_or_else(|| swarm.known().first().cloned().unwrap_or_default());
        let mut messages = Vec::new();
        let mut requested = Vec::new();
        if !digest.is_empty() {
            for index in swarm.missing(&digest) {
                messages.push(JsonValue::object([
                    ("bt".into(), JsonValue::String("request".into())),
                    ("index".into(), JsonValue::Number(index)),
                    ("info_hash".into(), JsonValue::String(digest.clone())),
                    ("peer".into(), JsonValue::String(peer.to_owned())),
                ]));
                requested.push(index);
            }
        }
        Ok((messages, digest, requested))
    }

    pub fn status(&self) -> Result<JsonValue, String> {
        let swarm = self.swarm.lock().map_err(|e| e.to_string())?;
        let state = swarm.state();
        let map = state
            .as_object()
            .and_then(|obj| obj.get("torrents"))
            .and_then(JsonValue::as_object)
            .cloned()
            .unwrap_or_default();
        let mut torrents = Vec::new();
        for digest in swarm.known() {
            if let Some(entry) = map.get(&digest) {
                let assembled = swarm
                    .assembled(&digest)
                    .map(JsonValue::String)
                    .unwrap_or(JsonValue::Null);
                if let Some(obj) = entry.as_object() {
                    torrents.push(JsonValue::object([
                        ("assembled".into(), assembled),
                        (
                            "complete".into(),
                            obj.get("complete")
                                .cloned()
                                .unwrap_or(JsonValue::Array(vec![])),
                        ),
                        (
                            "have".into(),
                            obj.get("have").cloned().unwrap_or(JsonValue::object([])),
                        ),
                        ("info_hash".into(), JsonValue::String(digest)),
                        (
                            "name".into(),
                            obj.get("name")
                                .cloned()
                                .unwrap_or(JsonValue::String(String::new())),
                        ),
                    ]));
                }
            }
        }
        Ok(JsonValue::object([
            ("event".into(), JsonValue::String("bt.status".into())),
            ("torrents".into(), JsonValue::Array(torrents)),
        ]))
    }

    fn serve_request(&self, data: &JsonValue) -> Option<JsonValue> {
        let obj = data.as_object()?;
        if obj.get("bt").and_then(JsonValue::as_str) != Some("request") {
            return None;
        }
        let peer = self.local_peer.lock().ok()?;
        if peer.is_empty() {
            return None;
        }
        let digest = obj.get("info_hash").and_then(JsonValue::as_str)?;
        let index = obj.get("index").and_then(JsonValue::as_i64)?;
        let payload = self.swarm.lock().ok()?.piece_hex(digest, index)?;
        Some(JsonValue::object([
            ("bt".into(), JsonValue::String("piece".into())),
            ("data".into(), JsonValue::String(payload)),
            ("index".into(), JsonValue::Number(index)),
            ("info_hash".into(), JsonValue::String(digest.to_owned())),
            ("peer".into(), JsonValue::String(peer.clone())),
        ]))
    }
}
