//! Node preset — SPEC/features/node-preset.md.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, Mutex};

use crate::canonical::JsonValue;
use crate::chain::TransferChain;
use crate::chain_driver::{make_driver, ouro_table, OURO_EPOCH, OURO_NONCE};
use crate::consensus_avalanche::Avalanche;
use crate::consensus_beacon::RandomnessBeacon;
use crate::consensus_ouroboros::Ouroboros;
use crate::consensus_pbft::Pbft;
use crate::consensus_poa::ProofOfAuthority;
use crate::consensus_poet::ProofOfElapsedTime;
use crate::consensus_pos::ProofOfStake;
use crate::consensus_pow::ProofOfWork;
use crate::consensus_pox::ProofOfTransfer;
use crate::crdt::CrdtKv;
use crate::ledger_balance::BalanceLedger;
use crate::ledger_utxo::UtxoLedger;
use crate::mesh::Mesh;
use crate::object::ApplicationObject;
use crate::pubsub::PubSub;

const CONSENSUS: &[&str] = &[
    "pow",
    "poa",
    "pos",
    "pbft",
    "poet",
    "avalanche",
    "beacon",
    "pox",
    "ouroboros",
];

enum PresetObject {
    Balance(BalanceLedger),
    Utxo(UtxoLedger),
    Crdt(CrdtKv),
    PubSub(PubSub),
    Pow(ProofOfWork),
    Poa(ProofOfAuthority),
    Pos(ProofOfStake),
    Pbft(Pbft),
    Poet(ProofOfElapsedTime),
    Avalanche(Avalanche),
    Beacon(RandomnessBeacon),
    Pox(ProofOfTransfer),
    Ouroboros(Ouroboros),
}

impl PresetObject {
    fn state_value(&self) -> JsonValue {
        match self {
            Self::Balance(o) => {
                let (balances, burned, nonces, supply) = o.state();
                JsonValue::object([
                    (
                        "balances".into(),
                        JsonValue::object(
                            balances
                                .iter()
                                .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                        ),
                    ),
                    ("burned".into(), JsonValue::Number(burned)),
                    (
                        "nonces".into(),
                        JsonValue::object(
                            nonces
                                .iter()
                                .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                        ),
                    ),
                    ("supply".into(), JsonValue::Number(supply)),
                ])
            }
            Self::Utxo(_) => JsonValue::Object(BTreeMap::new()),
            Self::Crdt(o) => o.state_value(),
            Self::PubSub(o) => o.state_value(),
            Self::Pow(o) => {
                let (blocks, canonical, height, tip) = o.state();
                JsonValue::object([
                    (
                        "blocks".into(),
                        JsonValue::Array(blocks.into_iter().map(JsonValue::String).collect()),
                    ),
                    (
                        "canonical".into(),
                        JsonValue::Array(canonical.into_iter().map(JsonValue::String).collect()),
                    ),
                    ("height".into(), JsonValue::Number(height)),
                    ("tip".into(), JsonValue::String(tip)),
                ])
            }
            Self::Poa(o) => {
                let (blocks, canonical, height, tip) = o.state();
                JsonValue::object([
                    (
                        "blocks".into(),
                        JsonValue::Array(blocks.into_iter().map(JsonValue::String).collect()),
                    ),
                    (
                        "canonical".into(),
                        JsonValue::Array(canonical.into_iter().map(JsonValue::String).collect()),
                    ),
                    ("height".into(), JsonValue::Number(height)),
                    ("tip".into(), JsonValue::String(tip)),
                ])
            }
            Self::Pos(o) => {
                let (head, last, slot) = o.state();
                JsonValue::object([
                    ("head".into(), JsonValue::String(head)),
                    ("last_proposer".into(), JsonValue::String(last)),
                    ("slot".into(), JsonValue::Number(slot)),
                ])
            }
            Self::Pbft(o) => {
                let (view, sequence, prepares, commits, executed) = o.state();
                JsonValue::object([
                    ("view".into(), JsonValue::Number(view)),
                    ("sequence".into(), JsonValue::Number(sequence)),
                    ("prepares".into(), JsonValue::Number(prepares as i64)),
                    ("commits".into(), JsonValue::Number(commits as i64)),
                    (
                        "executed".into(),
                        JsonValue::Array(
                            executed
                                .into_iter()
                                .map(|(digest, seq)| {
                                    JsonValue::object([
                                        ("digest".into(), JsonValue::String(digest)),
                                        ("seq".into(), JsonValue::Number(seq)),
                                    ])
                                })
                                .collect(),
                        ),
                    ),
                ])
            }
            Self::Poet(o) => {
                let (tickets, canonical, wait, winner) = o.state();
                JsonValue::object([
                    (
                        "tickets".into(),
                        JsonValue::Array(tickets.into_iter().map(JsonValue::String).collect()),
                    ),
                    (
                        "canonical".into(),
                        JsonValue::Array(canonical.into_iter().map(JsonValue::String).collect()),
                    ),
                    ("wait".into(), JsonValue::Number(wait as i64)),
                    ("winner".into(), JsonValue::String(winner)),
                ])
            }
            Self::Avalanche(o) => o.state_value(),
            Self::Beacon(o) => {
                let (pulses, height, output) = o.state();
                JsonValue::object([
                    (
                        "pulses".into(),
                        JsonValue::Array(pulses.iter().cloned().map(JsonValue::String).collect()),
                    ),
                    ("height".into(), JsonValue::Number(height)),
                    ("output".into(), JsonValue::String(output)),
                    (
                        "canonical".into(),
                        JsonValue::Array(pulses.into_iter().map(JsonValue::String).collect()),
                    ),
                ])
            }
            Self::Pox(o) => {
                let state = o.state();
                JsonValue::object([
                    ("height".into(), JsonValue::Number(state.0)),
                    ("tip".into(), JsonValue::String(state.1.clone())),
                    ("open_height".into(), JsonValue::Number(state.2)),
                    ("cycle".into(), JsonValue::Number(state.3)),
                    (
                        "canonical".into(),
                        JsonValue::Array(state.4.iter().cloned().map(JsonValue::String).collect()),
                    ),
                    (
                        "tenures".into(),
                        JsonValue::Array(state.5.iter().cloned().map(JsonValue::String).collect()),
                    ),
                    (
                        "bids".into(),
                        JsonValue::Array(state.6.iter().cloned().map(JsonValue::String).collect()),
                    ),
                    (
                        "stacks".into(),
                        JsonValue::Array(state.7.iter().cloned().map(JsonValue::String).collect()),
                    ),
                ])
            }
            Self::Ouroboros(o) => {
                let (slot, tip, canonical, blocks, epoch, nonce) = o.state();
                JsonValue::object([
                    ("slot".into(), JsonValue::Number(slot)),
                    ("tip".into(), JsonValue::String(tip)),
                    (
                        "canonical".into(),
                        JsonValue::Array(canonical.into_iter().map(JsonValue::String).collect()),
                    ),
                    (
                        "blocks".into(),
                        JsonValue::Array(blocks.into_iter().map(JsonValue::String).collect()),
                    ),
                    ("epoch".into(), JsonValue::Number(epoch)),
                    ("nonce".into(), JsonValue::String(nonce)),
                ])
            }
        }
    }

    fn is_valid(&self, message: &JsonValue) -> bool {
        match self {
            Self::Balance(o) => o.is_valid(message),
            Self::Utxo(o) => o.is_valid(message),
            Self::Crdt(o) => o.is_valid(message),
            Self::PubSub(o) => o.is_valid(message),
            Self::Pow(o) => o.is_valid(message),
            Self::Poa(o) => o.is_valid(message),
            Self::Pos(o) => o.is_valid(message),
            Self::Pbft(o) => o.is_valid(message),
            Self::Poet(o) => o.is_valid(message),
            Self::Avalanche(o) => o.is_valid(message),
            Self::Beacon(o) => o.is_valid(message),
            Self::Pox(o) => o.is_valid(message),
            Self::Ouroboros(o) => o.is_valid(message),
        }
    }

    fn add_message(&mut self, message: &JsonValue) {
        match self {
            Self::Balance(o) => {
                o.add_message(message, None);
            }
            Self::Utxo(o) => {
                o.add_message(message, None);
            }
            Self::Crdt(o) => {
                o.add_message(message, None);
            }
            Self::PubSub(o) => {
                o.add_message(message, None);
            }
            Self::Pow(o) => {
                o.add_message(message, None);
            }
            Self::Poa(o) => {
                o.add_message(message, None);
            }
            Self::Pos(o) => {
                o.add_message(message, None);
            }
            Self::Pbft(o) => {
                o.add_message(message, None);
            }
            Self::Poet(o) => {
                o.add_message(message, None);
            }
            Self::Avalanche(o) => {
                o.add_message(message, None);
            }
            Self::Beacon(o) => {
                o.add_message(message, None);
            }
            Self::Pox(o) => {
                o.add_message(message, None);
            }
            Self::Ouroboros(o) => {
                o.add_message(message, None);
            }
        }
    }
}

pub struct PresetHandle {
    pub listen_addr: String,
    chain: Option<Arc<Mutex<TransferChain>>>,
    object: Option<Arc<Mutex<PresetObject>>>,
    protocol: String,
    mesh: Arc<Mutex<Mesh>>,
}

impl PresetHandle {
    pub fn state(&self) -> JsonValue {
        if let Some(chain) = &self.chain {
            let guard = chain.lock().expect("lock");
            guard.state()
        } else if let Some(object) = &self.object {
            let guard = object.lock().expect("lock");
            guard.state_value()
        } else {
            JsonValue::Object(BTreeMap::new())
        }
    }

    pub fn submit(&self, message: &JsonValue) -> bool {
        if self.protocol == "transfer" {
            let chain = self.chain.as_ref().expect("transfer");
            let mut guard = chain.lock().expect("lock");
            if message
                .as_object()
                .map(|o| o.get("chain").and_then(JsonValue::as_str) == Some("transfer"))
                .unwrap_or(false)
            {
                if guard.accept_block(message) {
                    let _ = Mesh::broadcast(&self.mesh, "app.transfer", message.clone());
                    return true;
                }
                return false;
            }
            if guard.submit(message) {
                let _ = Mesh::broadcast(&self.mesh, "app.transfer", message.clone());
                return true;
            }
            return false;
        }
        let obj = self.object.as_ref().expect("object");
        let accepted = {
            let mut guard = obj.lock().expect("lock");
            if !guard.is_valid(message) {
                false
            } else {
                guard.add_message(message);
                true
            }
        };
        if !accepted {
            return false;
        }
        let app = format!("app.{}", self.protocol);
        let _ = Mesh::broadcast(&self.mesh, &app, message.clone());
        true
    }

    pub fn produce(&self, time: i64, producer: Option<&str>) -> Result<Option<JsonValue>, String> {
        let chain = self
            .chain
            .as_ref()
            .ok_or_else(|| "not a transfer node".to_string())?;
        let mut guard = chain.lock().expect("lock");
        let prod = producer.unwrap_or("alice");
        let block = guard.produce(time, prod)?;
        if let Some(ref blk) = block {
            let _ = Mesh::broadcast(&self.mesh, "app.transfer", blk.clone());
        }
        Ok(block)
    }

    pub fn connect(&self, addr: &str) -> Result<(), String> {
        Mesh::connect(&self.mesh, addr)
    }

    pub fn close(&self) {
        Mesh::close(&self.mesh);
    }
}

fn reject_unknown(
    config: &BTreeMap<String, JsonValue>,
    allowed: &BTreeSet<&str>,
) -> Result<(), String> {
    for key in config.keys() {
        if !allowed.contains(key.as_str()) {
            return Err(format!("unknown config key: {key}"));
        }
    }
    Ok(())
}

fn consensus_allowed(protocol: &str) -> BTreeSet<&'static str> {
    let mut set: BTreeSet<&'static str> =
        ["protocol", "listen", "peers", "udp"].into_iter().collect();
    let extra: &[&str] = match protocol {
        "pow" => &["difficulty"],
        "poa" => &["authorities"],
        "pbft" => &["replicas"],
        "poet" => &["seed"],
        "pox" => &["seed", "cycle_length", "stackers"],
        _ => &[],
    };
    for key in extra {
        set.insert(key);
    }
    set
}

fn wire_int(value: &JsonValue) -> Option<i64> {
    match value {
        JsonValue::Number(n) => Some(*n),
        _ => None,
    }
}

fn parse_stackers(value: &JsonValue) -> Result<Vec<(String, i64)>, String> {
    let items = value
        .as_array()
        .ok_or_else(|| "stackers must be non-empty".to_string())?;
    if items.is_empty() {
        return Err("stackers must be non-empty".into());
    }
    let mut out = Vec::new();
    for item in items {
        if item.as_array().is_some() {
            return Err("stackers entry must be an object".into());
        }
        let obj = item
            .as_object()
            .ok_or_else(|| "stackers entry must be an object".to_string())?;
        let locker = obj
            .get("locker")
            .and_then(JsonValue::as_str)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| "each locker must be a non-empty string".to_string())?;
        let amount = obj
            .get("amount")
            .and_then(wire_int)
            .filter(|n| *n >= 1)
            .ok_or_else(|| "each amount must be an integer >= 1".to_string())?;
        out.push((locker.to_owned(), amount));
    }
    Ok(out)
}

fn validate_consensus_config(
    protocol: &str,
    map: &BTreeMap<String, JsonValue>,
) -> Result<(), String> {
    reject_unknown(map, &consensus_allowed(protocol))?;
    match protocol {
        "pow" => {
            if let Some(difficulty) = map.get("difficulty") {
                let d = wire_int(difficulty).filter(|n| (1..=64).contains(n));
                if d.is_none() {
                    return Err("difficulty must be in 1..64".into());
                }
            }
        }
        "poa" => {
            if let Some(authorities) = map.get("authorities") {
                let list = authorities
                    .as_array()
                    .ok_or("authorities must be non-empty")?;
                if list.is_empty() {
                    return Err("authorities must be non-empty".into());
                }
                let mut seen = BTreeSet::new();
                for item in list {
                    let name = item
                        .as_str()
                        .filter(|s| !s.is_empty())
                        .ok_or_else(|| "each authority must be a non-empty string".to_string())?;
                    if !seen.insert(name) {
                        return Err("authorities must be distinct".into());
                    }
                }
            }
        }
        "pbft" => {
            if let Some(replicas) = map.get("replicas") {
                let list = replicas
                    .as_array()
                    .ok_or_else(|| "replicas must be unique non-empty ids".to_string())?;
                let mut names = Vec::new();
                for item in list {
                    let name = item
                        .as_str()
                        .filter(|s| !s.is_empty())
                        .ok_or_else(|| "replicas must be unique non-empty ids".to_string())?;
                    names.push(name);
                }
                if names.is_empty() || names.iter().collect::<BTreeSet<_>>().len() != names.len() {
                    return Err("replicas must be unique non-empty ids".into());
                }
            }
        }
        "poet" => {
            if let Some(seed) = map.get("seed") {
                let text = seed.as_str().filter(|s| !s.is_empty());
                if text.is_none() {
                    return Err("seed must be a non-empty string".into());
                }
            }
        }
        "pox" => {
            if let Some(seed) = map.get("seed") {
                let text = seed
                    .as_str()
                    .ok_or("seed must be 64 lowercase hex characters")?;
                if text.len() != 64 || !text.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
                {
                    return Err("seed must be 64 lowercase hex characters".into());
                }
            }
            if let Some(cycle) = map.get("cycle_length") {
                let n = wire_int(cycle).filter(|v| *v >= 1);
                if n.is_none() {
                    return Err("cycle_length must be an integer >= 1".into());
                }
            }
            if let Some(stackers) = map.get("stackers") {
                parse_stackers(stackers)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn json_bool(value: &JsonValue) -> Option<bool> {
    match value {
        JsonValue::Bool(flag) => Some(*flag),
        _ => None,
    }
}

pub fn start(config: &JsonValue) -> Result<PresetHandle, String> {
    let map = config
        .as_object()
        .ok_or_else(|| "config must be an object".to_string())?;
    let protocol = map
        .get("protocol")
        .and_then(JsonValue::as_str)
        .ok_or_else(|| "invalid protocol".to_string())?;
    let mut protocols: BTreeSet<&str> =
        BTreeSet::from(["transfer", "balance", "utxo", "crdt", "pubsub"]);
    for name in CONSENSUS {
        protocols.insert(name);
    }
    if !protocols.contains(protocol) {
        return Err("invalid protocol".to_string());
    }
    let listen = map
        .get("listen")
        .and_then(JsonValue::as_str)
        .unwrap_or("127.0.0.1:0");
    let peers = map
        .get("peers")
        .cloned()
        .unwrap_or(JsonValue::Array(Vec::new()));
    let udp = map.get("udp").and_then(json_bool).unwrap_or(false);

    if protocol == "transfer" {
        let allowed: BTreeSet<&str> = [
            "protocol",
            "consensus",
            "genesis",
            "reward",
            "authorities",
            "listen",
            "peers",
            "udp",
        ]
        .into_iter()
        .collect();
        reject_unknown(map, &allowed)?;
        let consensus = map
            .get("consensus")
            .and_then(JsonValue::as_str)
            .ok_or_else(|| "consensus required for transfer".to_string())?;
        let genesis_val = map
            .get("genesis")
            .ok_or_else(|| "genesis required".to_string())?;
        let genesis = json_i64_map(genesis_val)?;
        let reward = map.get("reward").and_then(JsonValue::as_i64).unwrap_or(0);
        let mut opts = JsonValue::Object(BTreeMap::new());
        if consensus == "poa" {
            let authorities = map
                .get("authorities")
                .and_then(JsonValue::as_array)
                .ok_or_else(|| "authorities required for poa".to_string())?;
            if authorities.is_empty() {
                return Err("authorities required for poa".to_string());
            }
            if let JsonValue::Object(ref mut obj) = opts {
                obj.insert(
                    "authorities".into(),
                    JsonValue::Array(
                        authorities
                            .iter()
                            .filter_map(|v| v.as_str().map(|s| JsonValue::String(s.to_owned())))
                            .collect(),
                    ),
                );
            }
        }
        let driver = make_driver(consensus, &opts)?;
        let chain = TransferChain::new(genesis, reward, Some(driver))?;
        let chain = Arc::new(Mutex::new(chain));
        let mesh = mesh_for_transfer(Arc::clone(&chain), listen, &peers, udp)?;
        let listen_addr = mesh.lock().expect("lock").listen_addr().to_owned();
        return Ok(PresetHandle {
            listen_addr,
            chain: Some(chain),
            object: None,
            protocol: protocol.to_owned(),
            mesh,
        });
    }

    if protocol == "balance" {
        let allowed: BTreeSet<&str> = ["protocol", "genesis", "listen", "peers", "udp"]
            .into_iter()
            .collect();
        reject_unknown(map, &allowed)?;
        let genesis = match map.get("genesis") {
            Some(v) => json_i64_map(v)?,
            None => crate::ledger_balance::default_allocations(),
        };
        let obj = PresetObject::Balance(BalanceLedger::new(genesis)?);
        return object_handle(obj, protocol, listen, &peers, udp);
    }

    if protocol == "utxo" {
        let allowed: BTreeSet<&str> = ["protocol", "genesis", "listen", "peers", "udp"]
            .into_iter()
            .collect();
        reject_unknown(map, &allowed)?;
        let genesis = match map.get("genesis") {
            Some(v) => json_i64_map(v)?,
            None => crate::ledger_utxo::default_allocations(),
        };
        let obj = PresetObject::Utxo(UtxoLedger::new(genesis)?);
        return object_handle(obj, protocol, listen, &peers, udp);
    }

    if protocol == "crdt" {
        let allowed: BTreeSet<&str> = ["protocol", "listen", "peers", "udp"].into_iter().collect();
        reject_unknown(map, &allowed)?;
        return object_handle(
            PresetObject::Crdt(CrdtKv::new()),
            protocol,
            listen,
            &peers,
            udp,
        );
    }

    if protocol == "pubsub" {
        let allowed: BTreeSet<&str> = ["protocol", "listen", "peers", "udp"].into_iter().collect();
        reject_unknown(map, &allowed)?;
        return object_handle(
            PresetObject::PubSub(PubSub::new()),
            protocol,
            listen,
            &peers,
            udp,
        );
    }

    validate_consensus_config(protocol, map)?;
    let obj = consensus_object(protocol, map)?;
    object_handle(obj, protocol, listen, &peers, udp)
}

fn json_i64_map(value: &JsonValue) -> Result<BTreeMap<String, i64>, String> {
    let obj = value
        .as_object()
        .ok_or_else(|| "genesis must be an object".to_string())?;
    let mut map = BTreeMap::new();
    for (k, v) in obj {
        let n = v
            .as_i64()
            .ok_or_else(|| "genesis values must be integers".to_string())?;
        map.insert(k.clone(), n);
    }
    Ok(map)
}

fn consensus_object(
    protocol: &str,
    config: &BTreeMap<String, JsonValue>,
) -> Result<PresetObject, String> {
    match protocol {
        "poa" => {
            let authorities: Vec<String> = config
                .get("authorities")
                .and_then(JsonValue::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(JsonValue::as_str)
                        .map(str::to_owned)
                        .collect()
                })
                .unwrap_or_else(|| vec!["alice".to_owned()]);
            Ok(PresetObject::Poa(ProofOfAuthority::new(&authorities)?))
        }
        "pow" => {
            let difficulty = config
                .get("difficulty")
                .and_then(JsonValue::as_i64)
                .unwrap_or(2) as u32;
            Ok(PresetObject::Pow(ProofOfWork::new(difficulty)?))
        }
        "pos" => Ok(PresetObject::Pos(ProofOfStake::default_set())),
        "pbft" => {
            let replicas = config.get("replicas").and_then(JsonValue::as_array);
            let pbft = match replicas {
                Some(items) => {
                    let names: Vec<&str> = items.iter().filter_map(JsonValue::as_str).collect();
                    Pbft::new(&names)?
                }
                None => Pbft::default_set(),
            };
            Ok(PresetObject::Pbft(pbft))
        }
        "poet" => {
            let seed = config
                .get("seed")
                .and_then(JsonValue::as_str)
                .unwrap_or("chaincraft-poet-genesis");
            Ok(PresetObject::Poet(ProofOfElapsedTime::new(seed)?))
        }
        "avalanche" => Ok(PresetObject::Avalanche(Avalanche::new("slush")?)),
        "beacon" => Ok(PresetObject::Beacon(RandomnessBeacon::new())),
        "pox" => {
            let default_seed = "0".repeat(64);
            let seed = config
                .get("seed")
                .and_then(JsonValue::as_str)
                .unwrap_or(&default_seed);
            let cycle = config
                .get("cycle_length")
                .and_then(JsonValue::as_i64)
                .unwrap_or(3);
            let stackers: Vec<(String, i64)> = match config.get("stackers") {
                Some(value) => parse_stackers(value)?,
                None => vec![("alice".to_owned(), 100)],
            };
            Ok(PresetObject::Pox(ProofOfTransfer::new(
                seed, cycle, &stackers,
            )?))
        }
        "ouroboros" => {
            let table = ouro_table();
            Ok(PresetObject::Ouroboros(Ouroboros::new(
                OURO_NONCE, OURO_EPOCH, &table,
            )?))
        }
        _ => Err("invalid protocol".into()),
    }
}

fn mesh_for_transfer(
    chain: Arc<Mutex<TransferChain>>,
    listen: &str,
    peers: &JsonValue,
    udp: bool,
) -> Result<Arc<Mutex<Mesh>>, String> {
    let mesh = Mesh::bind(listen)?;
    let chain_ref = Arc::clone(&chain);
    mesh.lock()
        .expect("lock")
        .set_on_app(Arc::new(move |app_type, data| {
            if app_type != "app.transfer" {
                return;
            }
            let mut guard = chain_ref.lock().expect("lock");
            if let Some(obj) = data.as_object() {
                if obj.get("chain").and_then(JsonValue::as_str) == Some("transfer") {
                    guard.accept_block(data);
                } else if obj.contains_key("signature") {
                    guard.submit(data);
                }
            }
        }));
    if udp {
        Mesh::bind_udp(&mesh)?;
    }
    if let Some(list) = peers.as_array() {
        for addr in list {
            if let Some(text) = addr.as_str() {
                if !text.is_empty() {
                    let _ = Mesh::connect(&mesh, text);
                }
            }
        }
    }
    Ok(mesh)
}

fn mesh_for_object(
    obj: Arc<Mutex<PresetObject>>,
    protocol: &str,
    listen: &str,
    peers: &JsonValue,
    udp: bool,
) -> Result<Arc<Mutex<Mesh>>, String> {
    let mesh = Mesh::bind(listen)?;
    let protocol_owned = protocol.to_owned();
    let obj_ref = Arc::clone(&obj);
    mesh.lock()
        .expect("lock")
        .set_on_app(Arc::new(move |app_type, data| {
            let want = format!("app.{protocol_owned}");
            if app_type != want {
                return;
            }
            let mut guard = obj_ref.lock().expect("lock");
            if guard.is_valid(data) {
                guard.add_message(data);
            }
        }));
    if udp {
        Mesh::bind_udp(&mesh)?;
    }
    if let Some(list) = peers.as_array() {
        for addr in list {
            if let Some(text) = addr.as_str() {
                if !text.is_empty() {
                    let _ = Mesh::connect(&mesh, text);
                }
            }
        }
    }
    Ok(mesh)
}

fn object_handle(
    obj: PresetObject,
    protocol: &str,
    listen: &str,
    peers: &JsonValue,
    udp: bool,
) -> Result<PresetHandle, String> {
    let obj = Arc::new(Mutex::new(obj));
    let mesh = mesh_for_object(Arc::clone(&obj), protocol, listen, peers, udp)?;
    let listen_addr = mesh.lock().expect("lock").listen_addr().to_owned();
    Ok(PresetHandle {
        listen_addr,
        chain: None,
        object: Some(obj),
        protocol: protocol.to_owned(),
        mesh,
    })
}
