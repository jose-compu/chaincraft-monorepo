//! Consensus drivers for chain.transfer — SPEC/features/chain-transfer.md.

use std::collections::HashMap;

use crate::canonical::{canonical_json, JsonValue};
use crate::chain::{block_id, ChainDriver};
use crate::consensus_avalanche::Avalanche;
use crate::consensus_beacon::{RandomnessBeacon, GENESIS_PREVIOUS};
use crate::consensus_ouroboros::{block_id as ouro_block_id, Ouroboros};
use crate::consensus_pbft::Pbft;
use crate::consensus_poa::{block_id as poa_block_id, proposer_for, ProofOfAuthority};
use crate::consensus_poet::ProofOfElapsedTime;
use crate::consensus_pos::{proposer_for as pos_proposer_for, ProofOfStake};
use crate::consensus_pow::{block_id as pow_block_id, meets_work, ProofOfWork};
use crate::consensus_pox::ProofOfTransfer;
use crate::object::{merkle_digest, ApplicationObject};
use crate::vdf;
use crate::vrf;

struct BaseDriver {
    chain_to_consensus: HashMap<String, String>,
    consensus_to_chain: HashMap<String, String>,
}

impl BaseDriver {
    fn new() -> Self {
        Self {
            chain_to_consensus: HashMap::new(),
            consensus_to_chain: HashMap::new(),
        }
    }

    fn remember(&mut self, chain_id: &str, consensus_id: &str) {
        self.chain_to_consensus
            .insert(chain_id.to_owned(), consensus_id.to_owned());
        self.consensus_to_chain
            .insert(consensus_id.to_owned(), chain_id.to_owned());
    }

    fn pow_parent(&self, chain_parent: &str) -> String {
        if chain_parent.is_empty() {
            return String::new();
        }
        self.chain_to_consensus
            .get(chain_parent)
            .cloned()
            .unwrap_or_default()
    }

    fn canonical_payloads(&self, consensus_canon: &[String]) -> Vec<String> {
        consensus_canon
            .iter()
            .filter_map(|id| self.consensus_to_chain.get(id).cloned())
            .collect()
    }
}

pub fn make_driver(consensus: &str, options: &JsonValue) -> Result<Box<dyn ChainDriver>, String> {
    let name = consensus.to_lowercase();
    let opts = options.as_object();
    match name.as_str() {
        "pow" => {
            let difficulty = opts
                .and_then(|o| o.get("difficulty"))
                .and_then(JsonValue::as_i64)
                .unwrap_or(1) as u32;
            Ok(Box::new(PowDriver::new(difficulty)))
        }
        "poa" => {
            let authorities = opts
                .and_then(|o| o.get("authorities"))
                .and_then(JsonValue::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(JsonValue::as_str)
                        .map(str::to_owned)
                        .collect::<Vec<_>>()
                })
                .unwrap_or_else(|| vec!["alice".to_owned()]);
            Ok(Box::new(PoaDriver::new(&authorities)?))
        }
        "pos" => Ok(Box::new(PosDriver::new())),
        "pbft" => Ok(Box::new(PbftDriver::new(None)?)),
        "poet" => {
            let seed = opts
                .and_then(|o| o.get("seed"))
                .and_then(JsonValue::as_str)
                .unwrap_or("chaincraft-poet-genesis");
            Ok(Box::new(PoetDriver::new(seed)))
        }
        "avalanche" => Ok(Box::new(AvalancheDriver::new())),
        "beacon" => {
            let beacon_name = opts
                .and_then(|o| o.get("name"))
                .and_then(JsonValue::as_str)
                .unwrap_or("alice");
            let sk_hex = opts.and_then(|o| o.get("sk")).and_then(JsonValue::as_str);
            let sk = sk_hex.and_then(|h| hex::decode(h).ok());
            Ok(Box::new(BeaconDriver::new(beacon_name, sk.as_deref())?))
        }
        "pox" => Ok(Box::new(PoxDriver::new())),
        "ouroboros" => Ok(Box::new(OuroborosDriver::new()?)),
        _ => Err(format!("unknown consensus: {consensus}")),
    }
}

pub struct PowDriver {
    base: BaseDriver,
    difficulty: u32,
    pow: ProofOfWork,
}

impl PowDriver {
    fn new(difficulty: u32) -> Self {
        Self {
            base: BaseDriver::new(),
            difficulty,
            pow: ProofOfWork::new(difficulty).expect("difficulty"),
        }
    }
}

impl ChainDriver for PowDriver {
    fn build_proof(&mut self, block: &JsonValue) -> Result<JsonValue, String> {
        let header = block
            .as_object()
            .and_then(|o| o.get("header"))
            .ok_or_else(|| "header required".to_string())?;
        let cid = block_id(header)?;
        let hdr = header.as_object().unwrap();
        let parent = self
            .base
            .pow_parent(hdr.get("parent").unwrap().as_str().unwrap());
        let height = hdr.get("height").unwrap().as_i64().unwrap();
        let producer = hdr.get("producer").unwrap().as_str().unwrap();
        let mut nonce = 0i64;
        loop {
            let digest = pow_block_id(height, producer, nonce, &parent, &cid);
            if meets_work(&digest, self.difficulty) {
                return Ok(JsonValue::object([
                    ("consensus".into(), JsonValue::String("pow".into())),
                    ("height".into(), JsonValue::Number(height)),
                    ("miner".into(), JsonValue::String(producer.to_owned())),
                    ("nonce".into(), JsonValue::Number(nonce)),
                    ("parent".into(), JsonValue::String(parent)),
                    ("payload".into(), JsonValue::String(cid)),
                    ("id".into(), JsonValue::String(digest)),
                ]));
            }
            nonce += 1;
        }
    }

    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool {
        let obj = match proof.as_object() {
            Some(o) if o.get("consensus").and_then(JsonValue::as_str) == Some("pow") => o,
            _ => return false,
        };
        let header = block.as_object().unwrap().get("header").unwrap();
        let cid = block_id(header).ok();
        let cid = match cid {
            Some(c) => c,
            None => return false,
        };
        if obj.get("payload").and_then(JsonValue::as_str) != Some(cid.as_str()) {
            return false;
        }
        if !self.pow.is_valid(proof) {
            return false;
        }
        self.pow.add_message(proof, None);
        let consensus_id = obj.get("id").unwrap().as_str().unwrap();
        self.base.remember(&cid, consensus_id);
        true
    }

    fn canonical(&self) -> Vec<String> {
        let (_, canon, _, _) = self.pow.state();
        self.base.canonical_payloads(&canon)
    }
}

pub struct PoaDriver {
    base: BaseDriver,
    authorities: Vec<String>,
    poa: ProofOfAuthority,
}

impl PoaDriver {
    fn new(authorities: &[String]) -> Result<Self, String> {
        Ok(Self {
            base: BaseDriver::new(),
            authorities: authorities.to_vec(),
            poa: ProofOfAuthority::new(authorities)?,
        })
    }
}

impl ChainDriver for PoaDriver {
    fn build_proof(&mut self, block: &JsonValue) -> Result<JsonValue, String> {
        let header = block
            .as_object()
            .and_then(|o| o.get("header"))
            .ok_or_else(|| "header required".to_string())?;
        let cid = block_id(header)?;
        let hdr = header.as_object().unwrap();
        let parent = self
            .base
            .pow_parent(hdr.get("parent").unwrap().as_str().unwrap());
        let height = hdr.get("height").unwrap().as_i64().unwrap();
        let proposer = hdr.get("producer").unwrap().as_str().unwrap();
        Ok(JsonValue::object([
            ("consensus".into(), JsonValue::String("poa".into())),
            ("height".into(), JsonValue::Number(height)),
            ("parent".into(), JsonValue::String(parent)),
            ("payload".into(), JsonValue::String(cid)),
            ("proposer".into(), JsonValue::String(proposer.to_owned())),
        ]))
    }

    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool {
        let obj = match proof.as_object() {
            Some(o) if o.get("consensus").and_then(JsonValue::as_str) == Some("poa") => o,
            _ => return false,
        };
        let header = block.as_object().unwrap().get("header").unwrap();
        let cid = block_id(header).ok();
        let cid = match cid {
            Some(c) => c,
            None => return false,
        };
        if obj.get("payload").and_then(JsonValue::as_str) != Some(cid.as_str()) {
            return false;
        }
        let height = header
            .as_object()
            .unwrap()
            .get("height")
            .unwrap()
            .as_i64()
            .unwrap();
        if obj.get("proposer").and_then(JsonValue::as_str)
            != Some(proposer_for(height, &self.authorities))
        {
            return false;
        }
        if !self.poa.is_valid(proof) {
            return false;
        }
        self.poa.add_message(proof, None);
        let digest = poa_block_id(
            obj.get("height").unwrap().as_i64().unwrap(),
            obj.get("parent").unwrap().as_str().unwrap(),
            obj.get("payload").unwrap().as_str().unwrap(),
            obj.get("proposer").unwrap().as_str().unwrap(),
        );
        self.base.remember(&cid, &digest);
        true
    }

    fn canonical(&self) -> Vec<String> {
        let (_, canon, _, _) = self.poa.state();
        self.base.canonical_payloads(&canon)
    }
}

pub struct PosDriver {
    pos: ProofOfStake,
    chain_ids: Vec<String>,
}

impl PosDriver {
    fn new() -> Self {
        Self {
            pos: ProofOfStake::default_set(),
            chain_ids: Vec::new(),
        }
    }
}

impl ChainDriver for PosDriver {
    fn build_proof(&mut self, block: &JsonValue) -> Result<JsonValue, String> {
        let header = block
            .as_object()
            .and_then(|o| o.get("header"))
            .ok_or_else(|| "header required".to_string())?;
        let cid = block_id(header)?;
        let hdr = header.as_object().unwrap();
        let slot = hdr.get("height").unwrap().as_i64().unwrap();
        let proposer = pos_proposer_for(slot, self.pos.stake_seed(), self.pos.stake_validators());
        Ok(JsonValue::object([
            ("consensus".into(), JsonValue::String("pos".into())),
            ("payload".into(), JsonValue::String(cid)),
            ("proposer".into(), JsonValue::String(proposer)),
            ("slot".into(), JsonValue::Number(slot)),
        ]))
    }

    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool {
        let obj = match proof.as_object() {
            Some(o) if o.get("consensus").and_then(JsonValue::as_str) == Some("pos") => o,
            _ => return false,
        };
        let header = block.as_object().unwrap().get("header").unwrap();
        let hdr = header.as_object().unwrap();
        if hdr.get("time").and_then(JsonValue::as_i64)
            != hdr.get("height").and_then(JsonValue::as_i64)
        {
            return false;
        }
        let cid = block_id(header).ok();
        let cid = match cid {
            Some(c) => c,
            None => return false,
        };
        if obj.get("payload").and_then(JsonValue::as_str) != Some(cid.as_str()) {
            return false;
        }
        if !self.pos.is_valid(proof) {
            return false;
        }
        self.pos.add_message(proof, None);
        self.chain_ids.push(cid);
        true
    }

    fn canonical(&self) -> Vec<String> {
        self.chain_ids.clone()
    }
}

pub struct PbftDriver {
    pbft: Pbft,
    executed: Vec<String>,
}

impl PbftDriver {
    fn new(replicas: Option<&Vec<JsonValue>>) -> Result<Self, String> {
        let pbft = match replicas {
            Some(items) => {
                let names: Vec<&str> = items.iter().filter_map(JsonValue::as_str).collect();
                Pbft::new(&names)?
            }
            None => Pbft::default_set(),
        };
        Ok(Self {
            pbft,
            executed: Vec::new(),
        })
    }
}

impl ChainDriver for PbftDriver {
    fn build_proof(&mut self, block: &JsonValue) -> Result<JsonValue, String> {
        let header = block
            .as_object()
            .and_then(|o| o.get("header"))
            .ok_or_else(|| "header required".to_string())?;
        let cid = block_id(header)?;
        let primary = self.pbft.primary_for(0);
        let mut prepares: Vec<JsonValue> = self
            .pbft
            .replica_list()
            .iter()
            .take(self.pbft.quorum_size())
            .map(|r| JsonValue::String(r.clone()))
            .collect();
        prepares.sort_by(|a, b| a.as_str().unwrap().cmp(b.as_str().unwrap()));
        let commits = prepares.clone();
        let digest = merkle_digest(&JsonValue::String(cid.clone())).map_err(|e| e.to_string())?;
        Ok(JsonValue::object([
            ("consensus".into(), JsonValue::String("pbft".into())),
            ("value".into(), JsonValue::String(cid)),
            ("digest".into(), JsonValue::String(digest)),
            ("primary".into(), JsonValue::String(primary.to_owned())),
            ("prepares".into(), JsonValue::Array(prepares)),
            ("commits".into(), JsonValue::Array(commits)),
        ]))
    }

    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool {
        let obj = match proof.as_object() {
            Some(o) if o.get("consensus").and_then(JsonValue::as_str) == Some("pbft") => o,
            _ => return false,
        };
        let header = block.as_object().unwrap().get("header").unwrap();
        let cid = block_id(header).ok();
        let cid = match cid {
            Some(c) => c,
            None => return false,
        };
        if obj.get("value").and_then(JsonValue::as_str) != Some(cid.as_str()) {
            return false;
        }
        let digest = match obj.get("digest").and_then(JsonValue::as_str) {
            Some(d) => d,
            None => return false,
        };
        if merkle_digest(&JsonValue::String(cid.clone()))
            .ok()
            .as_deref()
            != Some(digest)
        {
            return false;
        }
        let primary = self.pbft.primary_for(0);
        let seq = self.pbft.sequence_no();
        let mut msgs = vec![JsonValue::object([
            ("consensus".into(), JsonValue::String("pbft".into())),
            ("phase".into(), JsonValue::String("pre-prepare".into())),
            ("view".into(), JsonValue::Number(0)),
            ("sequence".into(), JsonValue::Number(seq)),
            ("digest".into(), JsonValue::String(digest.to_owned())),
            ("replica".into(), JsonValue::String(primary.to_owned())),
            ("value".into(), JsonValue::String(cid.clone())),
        ])];
        if let Some(preps) = obj.get("prepares").and_then(JsonValue::as_array) {
            for rep in preps {
                let rep = rep.as_str().unwrap();
                msgs.push(JsonValue::object([
                    ("consensus".into(), JsonValue::String("pbft".into())),
                    ("phase".into(), JsonValue::String("prepare".into())),
                    ("view".into(), JsonValue::Number(0)),
                    ("sequence".into(), JsonValue::Number(seq)),
                    ("digest".into(), JsonValue::String(digest.to_owned())),
                    ("replica".into(), JsonValue::String(rep.to_owned())),
                ]));
            }
        }
        if let Some(coms) = obj.get("commits").and_then(JsonValue::as_array) {
            for rep in coms {
                let rep = rep.as_str().unwrap();
                msgs.push(JsonValue::object([
                    ("consensus".into(), JsonValue::String("pbft".into())),
                    ("phase".into(), JsonValue::String("commit".into())),
                    ("view".into(), JsonValue::Number(0)),
                    ("sequence".into(), JsonValue::Number(seq)),
                    ("digest".into(), JsonValue::String(digest.to_owned())),
                    ("replica".into(), JsonValue::String(rep.to_owned())),
                ]));
            }
        }
        for msg in &msgs {
            if !self.pbft.is_valid(msg) {
                return false;
            }
            self.pbft.add_message(msg, None);
        }
        self.executed.push(cid);
        true
    }

    fn canonical(&self) -> Vec<String> {
        self.executed.clone()
    }
}

pub struct PoetDriver {
    height_seed: String,
    per_height: HashMap<i64, ProofOfElapsedTime>,
    canonical: Vec<String>,
}

impl PoetDriver {
    fn new(seed: &str) -> Self {
        Self {
            height_seed: seed.to_owned(),
            per_height: HashMap::new(),
            canonical: Vec::new(),
        }
    }
}

impl ChainDriver for PoetDriver {
    fn build_proof(&mut self, block: &JsonValue) -> Result<JsonValue, String> {
        let header = block
            .as_object()
            .and_then(|o| o.get("header"))
            .ok_or_else(|| "header required".to_string())?;
        let cid = block_id(header)?;
        let hdr = header.as_object().unwrap();
        let height = hdr.get("height").unwrap().as_i64().unwrap();
        if !self.per_height.contains_key(&height) {
            let seed = if height == 1 {
                self.height_seed.clone()
            } else {
                hdr.get("parent").unwrap().as_str().unwrap().to_owned()
            };
            self.per_height
                .insert(height, ProofOfElapsedTime::new(&seed)?);
        }
        let poet = self.per_height.get(&height).unwrap();
        let wait = 1u32;
        let proof_int = vdf::evaluate(poet.seed_bytes(), wait)?;
        let proof_hex = vdf::proof_to_hex(&proof_int);
        Ok(JsonValue::object([
            ("consensus".into(), JsonValue::String("poet".into())),
            (
                "author".into(),
                JsonValue::String(hdr.get("producer").unwrap().as_str().unwrap().to_owned()),
            ),
            ("payload".into(), JsonValue::String(cid)),
            ("wait".into(), JsonValue::Number(wait as i64)),
            ("proof".into(), JsonValue::String(proof_hex)),
        ]))
    }

    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool {
        let obj = match proof.as_object() {
            Some(o) if o.get("consensus").and_then(JsonValue::as_str) == Some("poet") => o,
            _ => return false,
        };
        let header = block.as_object().unwrap().get("header").unwrap();
        let cid = block_id(header).ok();
        let cid = match cid {
            Some(c) => c,
            None => return false,
        };
        if obj.get("payload").and_then(JsonValue::as_str) != Some(cid.as_str()) {
            return false;
        }
        let height = header
            .as_object()
            .unwrap()
            .get("height")
            .unwrap()
            .as_i64()
            .unwrap();
        if !self.per_height.contains_key(&height) {
            let seed = if height == 1 {
                self.height_seed.clone()
            } else {
                header
                    .as_object()
                    .unwrap()
                    .get("parent")
                    .unwrap()
                    .as_str()
                    .unwrap()
                    .to_owned()
            };
            self.per_height
                .insert(height, ProofOfElapsedTime::new(&seed).expect("seed"));
        }
        let poet = self.per_height.get_mut(&height).unwrap();
        if !poet.is_valid(proof) {
            return false;
        }
        poet.add_message(proof, None);
        if !self.canonical.contains(&cid) {
            self.canonical.push(cid);
        }
        true
    }

    fn canonical(&self) -> Vec<String> {
        self.canonical.clone()
    }
}

pub struct AvalancheDriver {
    per_height: HashMap<i64, Avalanche>,
    canonical: Vec<String>,
}

impl AvalancheDriver {
    fn new() -> Self {
        Self {
            per_height: HashMap::new(),
            canonical: Vec::new(),
        }
    }

    fn snow(&mut self, height: i64) -> &mut Avalanche {
        self.per_height
            .entry(height)
            .or_insert_with(|| Avalanche::with_params("snowball", 1, 1, 1).expect("params"))
    }
}

impl ChainDriver for AvalancheDriver {
    fn build_proof(&mut self, _block: &JsonValue) -> Result<JsonValue, String> {
        Ok(JsonValue::object([
            ("consensus".into(), JsonValue::String("avalanche".into())),
            (
                "messages".into(),
                JsonValue::Array(vec![
                    JsonValue::object([
                        ("color".into(), JsonValue::String("blue".into())),
                        ("consensus".into(), JsonValue::String("avalanche".into())),
                        ("op".into(), JsonValue::String("init".into())),
                    ]),
                    JsonValue::object([
                        ("consensus".into(), JsonValue::String("avalanche".into())),
                        ("op".into(), JsonValue::String("round".into())),
                        (
                            "votes".into(),
                            JsonValue::Array(vec![JsonValue::String("blue".into())]),
                        ),
                    ]),
                ]),
            ),
        ]))
    }

    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool {
        let obj = match proof.as_object() {
            Some(o) if o.get("consensus").and_then(JsonValue::as_str) == Some("avalanche") => o,
            _ => return false,
        };
        let header = block.as_object().unwrap().get("header").unwrap();
        let height = header
            .as_object()
            .unwrap()
            .get("height")
            .unwrap()
            .as_i64()
            .unwrap();
        let snow = self.snow(height);
        if let Some(messages) = obj.get("messages").and_then(JsonValue::as_array) {
            for msg in messages {
                if !snow.is_valid(msg) {
                    return false;
                }
                snow.add_message(msg, None);
            }
        }
        let final_ok = snow
            .state_value()
            .as_object()
            .and_then(|o| o.get("final"))
            .map(|v| matches!(v, JsonValue::Bool(true)))
            .unwrap_or(false);
        if !final_ok {
            return false;
        }
        let cid = block_id(header).ok();
        let cid = match cid {
            Some(c) => c,
            None => return false,
        };
        if !self.canonical.contains(&cid) {
            self.canonical.push(cid);
        }
        true
    }

    fn canonical(&self) -> Vec<String> {
        self.canonical.clone()
    }
}

pub struct BeaconDriver {
    name: String,
    sk: Option<Vec<u8>>,
    pk_hex: String,
    beacon: RandomnessBeacon,
    canonical: Vec<String>,
}

impl BeaconDriver {
    fn new(name: &str, sk: Option<&[u8]>) -> Result<Self, String> {
        let mut pk_hex = String::new();
        if let Some(key) = sk {
            let (_proof, _output, pk) = vrf::evaluate(b"bootstrap", key)?;
            pk_hex = hex::encode(pk);
        }
        Ok(Self {
            name: name.to_owned(),
            sk: sk.map(|s| s.to_vec()),
            pk_hex,
            beacon: RandomnessBeacon::new(),
            canonical: Vec::new(),
        })
    }

    fn pulse_message(&self, height: i64, previous: &str) -> Vec<u8> {
        let payload = JsonValue::object([
            ("height".into(), JsonValue::Number(height)),
            ("previous".into(), JsonValue::String(previous.to_owned())),
        ]);
        canonical_json(&payload).unwrap().into_bytes()
    }

    fn previous_output(&self) -> String {
        let (_, height, output) = self.beacon.state();
        if height < 0 {
            return GENESIS_PREVIOUS.to_owned();
        }
        output
    }
}

impl ChainDriver for BeaconDriver {
    fn build_proof(&mut self, block: &JsonValue) -> Result<JsonValue, String> {
        let header = block
            .as_object()
            .and_then(|o| o.get("header"))
            .ok_or_else(|| "header required".to_string())?;
        let hdr = header.as_object().unwrap();
        let beacon_height = hdr.get("height").unwrap().as_i64().unwrap() - 1;
        let previous = self.previous_output();
        let sk = self
            .sk
            .as_ref()
            .ok_or_else(|| "beacon driver requires sk".to_string())?;
        let message = self.pulse_message(beacon_height, &previous);
        let (proof, output, pk) = vrf::evaluate(&message, sk)?;
        Ok(JsonValue::object([
            ("consensus".into(), JsonValue::String("beacon".into())),
            ("height".into(), JsonValue::Number(beacon_height)),
            ("previous".into(), JsonValue::String(previous)),
            ("pk".into(), JsonValue::String(hex::encode(pk))),
            ("proof".into(), JsonValue::String(hex::encode(proof))),
            ("output".into(), JsonValue::String(hex::encode(output))),
        ]))
    }

    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool {
        let obj = match proof.as_object() {
            Some(o) if o.get("consensus").and_then(JsonValue::as_str) == Some("beacon") => o,
            _ => return false,
        };
        let header = block.as_object().unwrap().get("header").unwrap();
        let hdr = header.as_object().unwrap();
        if hdr.get("producer").and_then(JsonValue::as_str) != Some(self.name.as_str()) {
            return false;
        }
        if obj.get("pk").and_then(JsonValue::as_str) != Some(self.pk_hex.as_str()) {
            return false;
        }
        let expected_h = hdr.get("height").unwrap().as_i64().unwrap() - 1;
        if obj.get("height").and_then(JsonValue::as_i64) != Some(expected_h) {
            return false;
        }
        if !self.beacon.is_valid(proof) {
            return false;
        }
        self.beacon.add_message(proof, None);
        if let Ok(cid) = block_id(header) {
            self.canonical.push(cid);
        }
        true
    }

    fn canonical(&self) -> Vec<String> {
        self.canonical.clone()
    }
}

const POX_SEED: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
const POX_CYCLE: i64 = 3;
pub const OURO_NONCE: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
pub const OURO_EPOCH: i64 = 2;

pub fn ouro_table() -> Vec<(String, i64, String)> {
    let alice_sk = [0u8; 31].iter().chain([&3u8]).copied().collect::<Vec<_>>();
    let bob_sk =
        hex::decode("c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721").unwrap();
    let mut rows = Vec::new();
    for (sid, stake, sk) in [
        ("alice".to_owned(), 100i64, alice_sk),
        ("bob".to_owned(), 1i64, bob_sk),
    ] {
        let pk = vrf::evaluate(b"bootstrap", &sk).unwrap().2;
        rows.push((sid, stake, hex::encode(pk)));
    }
    rows
}

fn ouro_keys() -> HashMap<String, Vec<u8>> {
    let mut map = HashMap::new();
    map.insert(
        "alice".to_owned(),
        [0u8; 31].iter().chain([&3u8]).copied().collect(),
    );
    map.insert(
        "bob".to_owned(),
        hex::decode("c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721").unwrap(),
    );
    map
}

pub struct PoxDriver {
    pox: ProofOfTransfer,
    chain_ids: Vec<String>,
}

impl PoxDriver {
    fn new() -> Self {
        let stackers = vec![
            ("alice".to_owned(), 100i64),
            ("bob".to_owned(), 200i64),
            ("carol".to_owned(), 50i64),
        ];
        Self {
            pox: ProofOfTransfer::new(POX_SEED, POX_CYCLE, &stackers).expect("pox"),
            chain_ids: Vec::new(),
        }
    }
}

impl ChainDriver for PoxDriver {
    fn build_proof(&mut self, block: &JsonValue) -> Result<JsonValue, String> {
        let header = block
            .as_object()
            .and_then(|o| o.get("header"))
            .ok_or_else(|| "header required".to_string())?;
        let hdr = header.as_object().unwrap();
        let h = hdr.get("height").unwrap().as_i64().unwrap();
        let elected = self
            .pox
            .driver_elected_miner(h)
            .unwrap_or_else(|| hdr.get("producer").unwrap().as_str().unwrap().to_owned());
        let (tip, _) = self.pox.driver_tip();
        let prev = if h == 1 { String::new() } else { tip };
        let bids = vec![
            JsonValue::object([
                ("consensus".into(), JsonValue::String("pox".into())),
                ("kind".into(), JsonValue::String("bid".into())),
                ("miner".into(), JsonValue::String("alice".into())),
                ("btc_out".into(), JsonValue::Number(5)),
                ("block_height".into(), JsonValue::Number(h)),
            ]),
            JsonValue::object([
                ("consensus".into(), JsonValue::String("pox".into())),
                ("kind".into(), JsonValue::String("bid".into())),
                ("miner".into(), JsonValue::String("bob".into())),
                ("btc_out".into(), JsonValue::Number(6)),
                ("block_height".into(), JsonValue::Number(h)),
            ]),
            JsonValue::object([
                ("consensus".into(), JsonValue::String("pox".into())),
                ("kind".into(), JsonValue::String("bid".into())),
                ("miner".into(), JsonValue::String("carol".into())),
                ("btc_out".into(), JsonValue::Number(4)),
                ("block_height".into(), JsonValue::Number(h)),
            ]),
        ];
        let tenure = JsonValue::object([
            ("consensus".into(), JsonValue::String("pox".into())),
            ("kind".into(), JsonValue::String("tenure".into())),
            ("winner".into(), JsonValue::String(elected)),
            ("prev".into(), JsonValue::String(prev)),
            ("block_height".into(), JsonValue::Number(h)),
        ]);
        let mut messages = bids;
        messages.push(tenure);
        Ok(JsonValue::object([
            ("consensus".into(), JsonValue::String("pox".into())),
            ("messages".into(), JsonValue::Array(messages)),
        ]))
    }

    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool {
        let obj = match proof.as_object() {
            Some(o) if o.get("consensus").and_then(JsonValue::as_str) == Some("pox") => o,
            _ => return false,
        };
        let header = block.as_object().unwrap().get("header").unwrap();
        let height = header
            .as_object()
            .unwrap()
            .get("height")
            .unwrap()
            .as_i64()
            .unwrap();
        if let Some(elected) = self.pox.driver_elected_miner(height) {
            if header
                .as_object()
                .unwrap()
                .get("producer")
                .and_then(JsonValue::as_str)
                != Some(elected.as_str())
            {
                return false;
            }
        }
        if let Some(messages) = obj.get("messages").and_then(JsonValue::as_array) {
            for msg in messages {
                if !self.pox.is_valid(msg) {
                    return false;
                }
                self.pox.add_message(msg, None);
            }
        }
        if let Ok(cid) = block_id(header) {
            self.chain_ids.push(cid);
        }
        true
    }

    fn canonical(&self) -> Vec<String> {
        self.chain_ids.clone()
    }
}

pub struct OuroborosDriver {
    ouro: Ouroboros,
    chain_to_ouro: HashMap<String, String>,
    ouro_messages: HashMap<String, JsonValue>,
}

impl OuroborosDriver {
    fn new() -> Result<Self, String> {
        let table = ouro_table();
        Ok(Self {
            ouro: Ouroboros::new(OURO_NONCE, OURO_EPOCH, &table)?,
            chain_to_ouro: HashMap::new(),
            ouro_messages: HashMap::new(),
        })
    }
}

impl ChainDriver for OuroborosDriver {
    fn build_proof(&mut self, block: &JsonValue) -> Result<JsonValue, String> {
        let header = block
            .as_object()
            .and_then(|o| o.get("header"))
            .ok_or_else(|| "header required".to_string())?;
        let cid = block_id(header)?;
        let hdr = header.as_object().unwrap();
        let slot = hdr.get("height").unwrap().as_i64().unwrap();
        let parent = self
            .chain_to_ouro
            .get(hdr.get("parent").unwrap().as_str().unwrap())
            .cloned()
            .unwrap_or_default();
        let leader = hdr.get("producer").unwrap().as_str().unwrap();
        let table = ouro_table();
        let mut obj = Ouroboros::new(OURO_NONCE, OURO_EPOCH, &table)?;
        let (_, _, _, order, _, _) = self.ouro.state();
        for mid in &order {
            let msg = self.ouro_messages.get(mid).expect("message");
            obj.add_message(msg, None);
        }
        let (epoch, epoch_nonce) = obj.driver_epoch_nonce_for_slot(
            slot,
            if parent.is_empty() {
                None
            } else {
                Some(parent.as_str())
            },
        );
        let keys = ouro_keys();
        let sk = keys.get(leader).expect("leader key");
        let vrf_message = obj
            .driver_vrf_message(epoch, &epoch_nonce, slot, leader)
            .ok_or_else(|| "vrf message".to_string())?;
        let (proof, output, pk) = vrf::evaluate(&vrf_message, sk)?;
        Ok(JsonValue::object([
            ("consensus".into(), JsonValue::String("ouroboros".into())),
            ("slot".into(), JsonValue::Number(slot)),
            ("parent".into(), JsonValue::String(parent)),
            ("payload".into(), JsonValue::String(cid)),
            ("leader".into(), JsonValue::String(leader.to_owned())),
            ("pk".into(), JsonValue::String(hex::encode(pk))),
            ("proof".into(), JsonValue::String(hex::encode(proof))),
            ("output".into(), JsonValue::String(hex::encode(output))),
        ]))
    }

    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool {
        let obj = match proof.as_object() {
            Some(o) if o.get("consensus").and_then(JsonValue::as_str) == Some("ouroboros") => o,
            _ => return false,
        };
        let header = block.as_object().unwrap().get("header").unwrap();
        let cid = block_id(header).ok();
        let cid = match cid {
            Some(c) => c,
            None => return false,
        };
        if obj.get("payload").and_then(JsonValue::as_str) != Some(cid.as_str()) {
            return false;
        }
        if !self.ouro.is_valid(proof) {
            return false;
        }
        self.ouro.add_message(proof, None);
        let digest = ouro_block_id(
            obj.get("slot").unwrap().as_i64().unwrap(),
            obj.get("parent").unwrap().as_str().unwrap(),
            obj.get("payload").unwrap().as_str().unwrap(),
            obj.get("leader").unwrap().as_str().unwrap(),
            obj.get("pk").unwrap().as_str().unwrap(),
            obj.get("proof").unwrap().as_str().unwrap(),
            obj.get("output").unwrap().as_str().unwrap(),
        )
        .map_err(|e| e.to_string())
        .ok();
        let digest = match digest {
            Some(d) => d,
            None => return false,
        };
        self.ouro_messages.insert(digest.clone(), proof.clone());
        self.chain_to_ouro.insert(cid, digest);
        true
    }

    fn canonical(&self) -> Vec<String> {
        let (_, _, canon, _, _, _) = self.ouro.state();
        let mut payloads = Vec::new();
        for digest in &canon {
            if let Some(msg) = self.ouro_messages.get(digest) {
                if let Some(payload) = msg
                    .as_object()
                    .and_then(|o| o.get("payload"))
                    .and_then(JsonValue::as_str)
                {
                    payloads.push(payload.to_owned());
                }
            }
        }
        payloads
    }
}
