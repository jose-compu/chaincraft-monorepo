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
        let mut guard = obj.lock().expect("lock");
        if !guard.is_valid(message) {
            return false;
        }
        guard.add_message(message);
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

    let allowed: BTreeSet<&str> = ["protocol", "listen", "peers", "udp"].into_iter().collect();
    reject_unknown(map, &allowed)?;
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
            let stackers: Vec<(String, i64)> = config
                .get("stackers")
                .and_then(JsonValue::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|v| {
                            let arr = v.as_array()?;
                            Some((arr.first()?.as_str()?.to_owned(), arr.get(1)?.as_i64()?))
                        })
                        .collect()
                })
                .unwrap_or_else(|| vec![("alice".to_owned(), 100)]);
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
