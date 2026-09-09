//! Shared conformance vectors — SPEC/wire-v1.md and SPEC/semantics-v1.md.
//!
//! A failure here is a wire protocol violation. Never edit a vector to make a
//! test pass.

use std::any::Any;
use std::fs;
use std::path::PathBuf;

use chaincraft_core::canonical::{
    canonical_json, hex_to_bytes, parse_json, payload_digest, JsonValue,
};
use chaincraft_core::control;
use chaincraft_core::crypto::{public_key_hex, sign, verify, Algorithm};
use chaincraft_core::dedup::Deduplicator;
use chaincraft_core::discovery::{self, AddressBook, LocalDiscovery};
use chaincraft_core::envelope::Envelope;
use chaincraft_core::framing::{decode_datagram, encode_datagram, encode_frame, FrameReader};
use chaincraft_core::memento::StateMemento;
use chaincraft_core::object::{
    frontier_digest, merkle_digest, wins_replacement, ApplicationObject,
};
use chaincraft_core::pipeline::ObjectRegistry;
use chaincraft_core::{ecdsa, vdf, vrf};
use serde_json::Value;

fn vectors_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../conformance/vectors")
}

fn load(name: &str) -> Value {
    let path = vectors_dir().join(name);
    let text = fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    serde_json::from_str(&text).expect("vector json")
}

fn hex_bytes(text: &str) -> Vec<u8> {
    hex_to_bytes(text).unwrap_or_else(|e| panic!("hex: {e}"))
}

fn to_hex(bytes: &[u8]) -> String {
    chaincraft_core::canonical::bytes_to_hex(bytes)
}

// --- conformance objects, semantics-v1 §8 ----------------------------------

#[derive(Clone, Debug)]
struct Counter {
    seq: i64,
    total: i64,
    head: String,
}

impl Counter {
    fn new() -> Self {
        Self {
            seq: 0,
            total: 0,
            head: String::new(),
        }
    }

    fn state(&self) -> Value {
        serde_json::json!({
            "seq": self.seq,
            "total": self.total,
            "head": self.head,
        })
    }
}

impl ApplicationObject for Counter {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn is_valid(&self, message: &JsonValue) -> bool {
        let Some(obj) = message.as_object() else {
            return false;
        };
        let Some(delta) = obj.get("delta").and_then(JsonValue::as_i64) else {
            return false;
        };
        let Some(seq) = obj.get("seq").and_then(JsonValue::as_i64) else {
            return false;
        };
        if !(-100..=100).contains(&delta) {
            return false;
        }
        seq == self.seq + 1
    }

    fn add_message(
        &mut self,
        message: &JsonValue,
        frontier_state: Option<&StateMemento>,
    ) -> Option<StateMemento> {
        let obj = message.as_object().unwrap();
        let previous = self.head.clone();
        self.total += obj.get("delta").and_then(JsonValue::as_i64).unwrap();
        self.seq = obj.get("seq").and_then(JsonValue::as_i64).unwrap();
        let payload = JsonValue::object([
            ("previous_digest".into(), JsonValue::String(previous)),
            ("seq".into(), JsonValue::Number(self.seq)),
            ("total".into(), JsonValue::Number(self.total)),
            ("v".into(), JsonValue::Number(1)),
        ]);
        self.head = merkle_digest(&payload).unwrap();
        let frontier = frontier_state
            .map(|m| m.frontier_digests.clone())
            .unwrap_or_default();
        Some(StateMemento::normalize(&self.head, &frontier))
    }

    fn emit_state_memento(&self) -> StateMemento {
        StateMemento::normalize(&self.head, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        if self.head.is_empty() {
            Vec::new()
        } else {
            vec![self.head.clone()]
        }
    }

    fn is_merkelized(&self) -> bool {
        true
    }
}

#[derive(Clone, Debug)]
struct Mirror {
    count: i64,
    last_frontier: Vec<String>,
}

impl Mirror {
    fn new() -> Self {
        Self {
            count: 0,
            last_frontier: Vec::new(),
        }
    }

    fn state(&self) -> Value {
        serde_json::json!({
            "count": self.count,
            "last_frontier": self.last_frontier,
        })
    }
}

impl ApplicationObject for Mirror {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn is_valid(&self, message: &JsonValue) -> bool {
        match message.as_object() {
            Some(obj) => obj.get("reject_mirror") != Some(&JsonValue::Bool(true)),
            None => true,
        }
    }

    fn add_message(
        &mut self,
        _message: &JsonValue,
        frontier_state: Option<&StateMemento>,
    ) -> Option<StateMemento> {
        self.count += 1;
        self.last_frontier = frontier_state
            .map(|m| m.frontier_digests.clone())
            .unwrap_or_default();
        None
    }

    fn emit_state_memento(&self) -> StateMemento {
        StateMemento::normalize("", &self.last_frontier)
    }
}

fn build_registry() -> ObjectRegistry {
    let mut registry = ObjectRegistry::new();
    registry.register("counter", Box::new(Counter::new()));
    registry.register("mirror", Box::new(Mirror::new()));
    registry
}

fn snapshot(registry: &ObjectRegistry) -> Value {
    let counter = registry
        .get("counter")
        .unwrap()
        .as_any()
        .downcast_ref::<Counter>()
        .unwrap();
    let mirror = registry
        .get("mirror")
        .unwrap()
        .as_any()
        .downcast_ref::<Mirror>()
        .unwrap();
    serde_json::json!({
        "counter": counter.state(),
        "mirror": mirror.state(),
    })
}

// --- Level 0 ---------------------------------------------------------------

#[test]
fn canonical_valid() {
    let doc = load("canonical-json.json");
    for case in doc["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let parsed = parse_json(case["input_json"].as_str().unwrap())
            .unwrap_or_else(|e| panic!("{name}: parse {e}"));
        let encoded = canonical_json(&parsed).unwrap_or_else(|e| panic!("{name}: encode {e}"));
        assert_eq!(encoded, case["canonical"].as_str().unwrap(), "{name}");
    }
}

#[test]
fn canonical_invalid() {
    let doc = load("canonical-json.json");
    for case in doc["invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let result =
            parse_json(case["input_json"].as_str().unwrap()).and_then(|v| canonical_json(&v));
        assert!(result.is_err(), "{name} should have been rejected");
        assert!(
            result.unwrap_err().is_canonical(),
            "{name} wrong error class"
        );
    }
}

#[test]
fn payload_digests() {
    let doc = load("digest.json");
    for case in doc["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let data = parse_json(case["data_json"].as_str().unwrap()).unwrap();
        assert_eq!(
            canonical_json(&data).unwrap(),
            case["canonical"].as_str().unwrap(),
            "{name}"
        );
        assert_eq!(
            payload_digest(&data).unwrap(),
            case["digest"].as_str().unwrap(),
            "{name}"
        );
    }
}

#[test]
fn envelope_valid() {
    let doc = load("envelope.json");
    let now = doc["now_ms"].as_i64();
    for case in doc["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let data = parse_json(case["data_json"].as_str().unwrap()).unwrap();
        let env = Envelope::build(
            case["type"].as_str().unwrap(),
            data,
            Some(case["ts"].as_i64().unwrap()),
        )
        .unwrap();
        assert_eq!(env.id, case["id"].as_str().unwrap(), "{name}");
        assert_eq!(
            env.to_json().unwrap(),
            case["canonical"].as_str().unwrap(),
            "{name}"
        );
        let parsed = Envelope::parse_text(case["canonical"].as_str().unwrap(), now).unwrap();
        assert_eq!(
            parsed.to_json().unwrap(),
            case["canonical"].as_str().unwrap(),
            "{name}"
        );
    }
}

#[test]
fn envelope_invalid() {
    let doc = load("envelope.json");
    let now = doc["now_ms"].as_i64();
    for case in doc["invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let result = Envelope::parse_text(case["envelope_json"].as_str().unwrap(), now);
        assert!(result.is_err(), "{name} should have been rejected");
        assert!(
            result.unwrap_err().is_protocol(),
            "{name} wrong error class"
        );
    }
}

#[test]
fn framing_valid() {
    let doc = load("framing.json");
    for case in doc["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let frame = encode_frame(&hex_bytes(case["body_hex"].as_str().unwrap())).unwrap();
        assert_eq!(
            to_hex(&frame),
            case["frame_hex"].as_str().unwrap(),
            "{name}"
        );
    }
}

#[test]
fn framing_stream() {
    let doc = load("framing.json");
    for case in doc["stream"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut reader = FrameReader::new();
        let mut received = Vec::new();
        for chunk in case["chunks_hex"].as_array().unwrap() {
            received.extend(reader.feed(&hex_bytes(chunk.as_str().unwrap())).unwrap());
        }
        let got: Vec<String> = received.iter().map(|b| to_hex(b)).collect();
        let expected: Vec<String> = case["frames_hex"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(got, expected, "{name}");
    }
}

#[test]
fn framing_invalid() {
    let doc = load("framing.json");
    for case in doc["invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut reader = FrameReader::new();
        let result = reader.feed(&hex_bytes(case["input_hex"].as_str().unwrap()));
        assert!(result.is_err(), "{name}");
        assert!(result.unwrap_err().is_framing(), "{name}");
    }
}

#[test]
fn framing_udp_valid() {
    let doc = load("framing.json");
    for case in doc["udp_valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let body = hex_bytes(case["body_hex"].as_str().unwrap());
        assert_eq!(encode_datagram(&body).unwrap(), body, "{name}");
        assert_eq!(decode_datagram(&body).unwrap(), body, "{name}");
    }
}

#[test]
fn framing_udp_invalid() {
    let doc = load("framing.json");
    for case in doc["udp_invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let data = if case["input_hex"].is_null() {
            vec![0u8; case["input_length"].as_u64().unwrap() as usize]
        } else {
            hex_bytes(case["input_hex"].as_str().unwrap())
        };
        let dec = decode_datagram(&data);
        let enc = encode_datagram(&data);
        assert!(dec.is_err() && enc.is_err(), "{name}");
        assert!(dec.unwrap_err().is_framing(), "{name}");
        assert!(enc.unwrap_err().is_framing(), "{name}");
    }
}

fn control_builder(name: &str, ts: i64) -> Envelope {
    match name {
        "hello minimal" => control::hello("py-chaincraft/1.0.0", None, None, Some(ts)).unwrap(),
        "hello with listen and caps" => control::hello(
            "py-chaincraft/1.0.0",
            Some(&["udp", "gossip", "digest-sync"]),
            Some("10.0.0.2:9735"),
            Some(ts),
        )
        .unwrap(),
        "peers request" => control::peers_request(Some(ts)).unwrap(),
        "peers response" => control::peers(&["10.0.0.2:9735", "10.0.0.3:9735"], Some(ts)).unwrap(),
        "digest request" => control::digest_request("BalanceLedger", Some(ts)).unwrap(),
        "digest response" => control::digest(
            "BalanceLedger",
            &"ab".repeat(32),
            &[&"cd".repeat(32)],
            Some(ts),
        )
        .unwrap(),
        "messages request" => {
            control::messages_request("BalanceLedger", &"ab".repeat(32), Some(ts)).unwrap()
        }
        "messages response" => {
            let inner = Envelope::build(
                "app.t",
                JsonValue::object([("n".into(), JsonValue::Number(1))]),
                Some(ts),
            )
            .unwrap();
            control::messages("BalanceLedger", &[inner], Some(ts)).unwrap()
        }
        other => panic!("no builder for {other}"),
    }
}

#[test]
fn control_valid() {
    let doc = load("control.json");
    let now = doc["now_ms"].as_i64();
    for case in doc["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let parsed = Envelope::parse_text(case["canonical"].as_str().unwrap(), now).unwrap();
        assert_eq!(parsed.type_name, case["type"].as_str().unwrap(), "{name}");
        assert_eq!(parsed.id, case["id"].as_str().unwrap(), "{name}");
        let built = control_builder(name, parsed.ts);
        assert_eq!(
            built.to_json().unwrap(),
            case["canonical"].as_str().unwrap(),
            "{name}"
        );
    }
}

#[test]
fn control_invalid() {
    let doc = load("control.json");
    let now = doc["now_ms"].as_i64();
    for case in doc["invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let env = Envelope::parse_text(case["envelope_json"].as_str().unwrap(), now).unwrap();
        let result = control::parse_hello(&env);
        assert!(result.is_err(), "{name}");
        assert!(result.unwrap_err().is_protocol(), "{name}");
    }
}

#[test]
fn signatures_valid() {
    let doc = load("signatures.json");
    for case in doc["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let alg = Algorithm::parse(case["alg"].as_str().unwrap()).unwrap();
        let secret = hex_bytes(case["secret_key"].as_str().unwrap());
        let message = hex_bytes(case["message"].as_str().unwrap());
        let aux = hex_bytes(case["aux"].as_str().unwrap());
        assert_eq!(
            public_key_hex(alg, &secret).unwrap(),
            case["public_key"].as_str().unwrap(),
            "{name} pubkey"
        );
        let produced = sign(alg, &message, &secret, Some(&aux)).unwrap();
        assert_eq!(
            to_hex(&produced.signature),
            case["signature"].as_str().unwrap(),
            "{name} deterministic signing"
        );
        assert!(verify(
            case["alg"].as_str().unwrap(),
            &message,
            &produced.signature,
            &hex_bytes(case["public_key"].as_str().unwrap())
        ));
        if let Some(canonical) = case.get("canonical").and_then(Value::as_str) {
            let env = Envelope::parse_text(canonical, Some(10_000_000_000_000)).unwrap();
            assert!(env.verify(), "{name} envelope verify");
        }
    }
}

#[test]
fn signatures_invalid() {
    let doc = load("signatures.json");
    for case in doc["invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let ok = verify(
            case["alg"].as_str().unwrap(),
            &hex_bytes(case["message"].as_str().unwrap()),
            &hex_bytes(case["signature"].as_str().unwrap()),
            &hex_bytes(case["public_key"].as_str().unwrap()),
        );
        assert!(!ok, "{name} must verify as false");
    }
}

#[test]
fn dedup_sequence() {
    let doc = load("dedup.json");
    let now = doc["now_ms"].as_i64();
    for case in doc["sequence"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut dedup = Deduplicator::new(case["capacity"].as_u64().unwrap() as usize);
        for (index, step) in case["steps"].as_array().unwrap().iter().enumerate() {
            let env = Envelope::parse_text(step["canonical"].as_str().unwrap(), now).unwrap();
            let where_ = format!("{name} step {index}");
            assert_eq!(env.id, step["id"].as_str().unwrap(), "{where_}");
            assert_eq!(
                dedup.should_process(&env),
                step["should_process"].as_bool().unwrap(),
                "{where_} process"
            );
            assert_eq!(
                dedup.should_relay(&env),
                step["should_relay"].as_bool().unwrap(),
                "{where_} relay"
            );
            assert_eq!(
                dedup.seen.len(),
                step["seen_size"].as_u64().unwrap() as usize,
                "{where_} size"
            );
        }
    }
}

// --- Level 1 ---------------------------------------------------------------

#[test]
fn memento_normalize() {
    let doc = load("memento.json");
    for case in doc["normalize"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let frontier: Vec<String> = case["input"]["frontier_digests"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        let memento = StateMemento::normalize(
            case["input"]["canonical_digest"].as_str().unwrap(),
            &frontier,
        );
        let got = serde_json::to_value(serde_json::json!({
            "canonical_digest": memento.canonical_digest,
            "frontier_digests": memento.frontier_digests,
            "revision": memento.revision,
            "metadata": {},
        }))
        .unwrap();
        assert_eq!(got, case["expected"], "{name}");
    }
}

#[test]
fn memento_reorg() {
    let doc = load("memento.json");
    for case in doc["reorg"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let current_front: Vec<String> = case["current"]["frontier_digests"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        let current = StateMemento::normalize(
            case["current"]["canonical_digest"].as_str().unwrap(),
            &current_front,
        );
        let previous = if case["previous"].is_null() {
            None
        } else {
            let front: Vec<String> = case["previous"]["frontier_digests"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().unwrap().to_string())
                .collect();
            Some(StateMemento::normalize(
                case["previous"]["canonical_digest"].as_str().unwrap(),
                &front,
            ))
        };
        assert_eq!(
            current.indicates_reorg_against(previous.as_ref()),
            case["expected"].as_bool().unwrap(),
            "{name}"
        );
    }
}

#[test]
fn merkle_vectors() {
    let doc = load("memento.json");
    for case in doc["merkle"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let payload = parse_json(case["payload_json"].as_str().unwrap()).unwrap();
        assert_eq!(
            canonical_json(&payload).unwrap(),
            case["canonical"].as_str().unwrap(),
            "{name}"
        );
        assert_eq!(
            merkle_digest(&payload).unwrap(),
            case["digest"].as_str().unwrap(),
            "{name}"
        );
    }
}

#[test]
fn frontier_vectors() {
    let doc = load("memento.json");
    for case in doc["frontier"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let heads: Vec<String> = case["heads"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(
            frontier_digest(&heads).unwrap(),
            case["digest"].as_str().unwrap(),
            "{name}"
        );
    }
}

#[test]
fn pipeline_replay() {
    let doc = load("pipeline.json");
    assert_eq!(doc["registry"], serde_json::json!(build_registry().names()));
    for case in doc["replay"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut registry = build_registry();
        for (index, step) in case["steps"].as_array().unwrap().iter().enumerate() {
            let message = parse_json(step["message_json"].as_str().unwrap()).unwrap();
            let result = registry.apply(&message);
            let where_ = format!("{name} step {index}");
            assert_eq!(
                result.accepted,
                step["accepted"].as_bool().unwrap(),
                "{where_} accepted"
            );
            let rejected = result.rejected_by.as_deref();
            let expected = step["rejected_by"].as_str();
            assert_eq!(rejected, expected, "{where_} rejected_by");
            let state = snapshot(&registry);
            assert_eq!(state["counter"], step["counter"], "{where_} counter");
            assert_eq!(state["mirror"], step["mirror"], "{where_} mirror");
        }
    }
}

#[test]
fn replacement_tiebreak() {
    let doc = load("pipeline.json");
    for case in doc["tiebreak"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        assert_eq!(
            wins_replacement(
                case["candidate"]["rank"].as_i64().unwrap(),
                case["candidate"]["digest"].as_str().unwrap(),
                case["incumbent"]["rank"].as_i64().unwrap(),
                case["incumbent"]["digest"].as_str().unwrap(),
            ),
            case["expected"].as_bool().unwrap(),
            "{name}"
        );
    }
}

#[test]
fn ecdsa_valid() {
    let doc = load("ecdsa.json");
    for case in doc["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let key = hex_bytes(case["secret_key"].as_str().unwrap());
        let message = hex_bytes(case["message_hex"].as_str().unwrap());
        let pk = ecdsa::public_key(&key).unwrap();
        assert_eq!(
            to_hex(&pk),
            case["public_key"].as_str().unwrap(),
            "{name} pubkey"
        );
        let sig = ecdsa::sign(&message, &key).unwrap();
        assert_eq!(
            to_hex(&sig),
            case["signature"].as_str().unwrap(),
            "{name} signature"
        );
        assert!(
            ecdsa::verify(
                &message,
                &hex_bytes(case["signature"].as_str().unwrap()),
                &hex_bytes(case["public_key"].as_str().unwrap())
            ),
            "{name} verify"
        );
    }
}

#[test]
fn ecdsa_invalid() {
    let doc = load("ecdsa.json");
    for case in doc["invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        assert!(
            !ecdsa::verify(
                &hex_bytes(case["message_hex"].as_str().unwrap()),
                &hex_bytes(case["signature"].as_str().unwrap()),
                &hex_bytes(case["public_key"].as_str().unwrap())
            ),
            "{name}"
        );
    }
}

#[test]
fn vdf_valid() {
    let doc = load("vdf.json");
    for case in doc["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let seed = hex_bytes(case["seed_hex"].as_str().unwrap());
        let t = case["t"].as_u64().unwrap() as u32;
        let proof = vdf::evaluate(&seed, t).unwrap();
        assert_eq!(
            vdf::proof_to_hex(&proof),
            case["proof"].as_str().unwrap(),
            "{name}"
        );
        assert!(vdf::verify(&seed, t, &proof), "{name} verify");
    }
}

#[test]
fn vdf_invalid() {
    let doc = load("vdf.json");
    for case in doc["invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let proof = vdf::hex_to_proof(case["proof"].as_str().unwrap()).unwrap();
        assert!(
            !vdf::verify(
                &hex_bytes(case["seed_hex"].as_str().unwrap()),
                case["t"].as_u64().unwrap() as u32,
                &proof
            ),
            "{name}"
        );
    }
}

#[test]
fn vrf_valid() {
    let doc = load("vrf.json");
    for case in doc["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let message = hex_bytes(case["message_hex"].as_str().unwrap());
        let key = hex_bytes(case["secret_key"].as_str().unwrap());
        let (proof, output, pk) = vrf::evaluate(&message, &key).unwrap();
        assert_eq!(
            to_hex(&pk),
            case["public_key"].as_str().unwrap(),
            "{name} pubkey"
        );
        assert_eq!(
            to_hex(&proof),
            case["proof"].as_str().unwrap(),
            "{name} proof"
        );
        assert_eq!(
            to_hex(&output),
            case["output"].as_str().unwrap(),
            "{name} output"
        );
        assert!(
            vrf::verify(&message, &proof, &pk, Some(&output)),
            "{name} verify"
        );
    }
}

#[test]
fn vrf_invalid() {
    let doc = load("vrf.json");
    for case in doc["invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        assert!(
            !vrf::verify(
                &hex_bytes(case["message_hex"].as_str().unwrap()),
                &hex_bytes(case["proof"].as_str().unwrap()),
                &hex_bytes(case["public_key"].as_str().unwrap()),
                Some(&hex_bytes(case["output"].as_str().unwrap()))
            ),
            "{name}"
        );
    }
}

fn json_strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .unwrap()
        .iter()
        .map(|item| item.as_str().unwrap().to_owned())
        .collect()
}

fn assert_book(book: &AddressBook, step: &Value, where_: &str) {
    assert_eq!(
        book.len(),
        step["size"].as_u64().unwrap() as usize,
        "{where_} size"
    );
    assert_eq!(
        book.addresses(),
        json_strings(&step["book"]),
        "{where_} book"
    );
    assert_eq!(
        book.advertise(),
        json_strings(&step["advertised"]),
        "{where_} advertised"
    );
}

#[test]
fn discovery_peer_valid() {
    let doc = load("discovery-peer.json");
    for case in doc["valid"].as_array().unwrap() {
        let address = case["address"].as_str().unwrap();
        assert!(discovery::is_valid_address(address), "{address}");
    }
}

#[test]
fn discovery_peer_invalid() {
    let doc = load("discovery-peer.json");
    for case in doc["invalid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let address = case["address"].as_str().unwrap();
        assert!(!discovery::is_valid_address(address), "{name}");
    }
}

#[test]
fn discovery_peer_sequence() {
    let doc = load("discovery-peer.json");
    let timeout = doc["default_timeout_ms"].as_i64().unwrap();
    for case in doc["sequence"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut book = AddressBook::new(
            Some(case["listen"].as_str().unwrap()),
            case["capacity"].as_u64().unwrap() as usize,
            timeout,
        )
        .unwrap();
        for (index, step) in case["steps"].as_array().unwrap().iter().enumerate() {
            let where_ = format!("{name} step {index}");
            match step["op"].as_str().unwrap() {
                "insert" => {
                    assert_eq!(
                        book.insert(
                            step["address"].as_str().unwrap(),
                            step["now_ms"].as_i64().unwrap()
                        ),
                        step["added"].as_bool().unwrap(),
                        "{where_}"
                    );
                }
                "ingest" => {
                    assert_eq!(
                        book.ingest(
                            &json_strings(&step["addresses"]),
                            step["now_ms"].as_i64().unwrap(),
                            step["solicited"].as_bool().unwrap()
                        ),
                        step["added"].as_u64().unwrap() as usize,
                        "{where_}"
                    );
                }
                "sweep" => {
                    assert_eq!(
                        book.sweep(step["now_ms"].as_i64().unwrap()),
                        step["expired"].as_u64().unwrap() as usize,
                        "{where_}"
                    );
                }
                "advertise" => {
                    assert_eq!(
                        book.advertise(),
                        json_strings(&step["advertised"]),
                        "{where_}"
                    );
                }
                other => panic!("unknown op {other}"),
            }
            assert_book(&book, step, &where_);
        }
    }
}

#[test]
fn discovery_local_sequence() {
    let doc = load("discovery-local.json");
    for case in doc["sequence"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut book =
            AddressBook::new(Some(case["listen"].as_str().unwrap()), 50, 120_000).unwrap();
        let local = LocalDiscovery::new(case["enabled"].as_bool().unwrap());
        for (index, step) in case["steps"].as_array().unwrap().iter().enumerate() {
            let where_ = format!("{name} step {index}");
            match step["op"].as_str().unwrap() {
                "insert" => {
                    assert_eq!(
                        book.insert(
                            step["address"].as_str().unwrap(),
                            step["now_ms"].as_i64().unwrap()
                        ),
                        step["added"].as_bool().unwrap(),
                        "{where_}"
                    );
                }
                "request" => {
                    let peer = step["peer"].as_str().unwrap();
                    assert_eq!(
                        local.request(&mut book, peer),
                        step["ok"].as_bool().unwrap(),
                        "{where_}"
                    );
                    assert_eq!(
                        book.is_solicited(peer),
                        step["solicited"].as_bool().unwrap(),
                        "{where_}"
                    );
                }
                "reply" => {
                    let peers = local.reply(&book);
                    if step["peers"].is_null() {
                        assert!(peers.is_none(), "{where_}");
                    } else {
                        assert_eq!(peers.unwrap(), json_strings(&step["peers"]), "{where_}");
                    }
                }
                "accept" => {
                    let from = step["from"].as_str().unwrap();
                    assert_eq!(
                        local.accept(
                            &mut book,
                            from,
                            &json_strings(&step["addresses"]),
                            step["now_ms"].as_i64().unwrap()
                        ),
                        step["added"].as_u64().unwrap() as usize,
                        "{where_}"
                    );
                    assert_eq!(
                        book.is_solicited(from),
                        step["solicited"].as_bool().unwrap(),
                        "{where_}"
                    );
                }
                other => panic!("unknown op {other}"),
            }
            assert_book(&book, step, &where_);
        }
    }
}

#[test]
fn vector_files_declare_feature() {
    for name in [
        "canonical-json.json",
        "digest.json",
        "envelope.json",
        "framing.json",
        "control.json",
        "signatures.json",
        "dedup.json",
        "memento.json",
        "pipeline.json",
        "ecdsa.json",
        "vdf.json",
        "vrf.json",
        "discovery-peer.json",
        "discovery-local.json",
    ] {
        let doc = load(name);
        assert!(doc.get("feature").is_some(), "{name} missing feature");
        assert_eq!(doc["wire_version"].as_i64(), Some(1), "{name}");
    }
}
