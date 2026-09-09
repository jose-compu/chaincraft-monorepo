//! Control messages — SPEC/wire-v1.md §5.

use std::collections::{BTreeMap, BTreeSet};

use crate::canonical::JsonValue;
use crate::envelope::{Envelope, PROTOCOL_VERSION};
use crate::error::{Error, Result};

pub const HELLO: &str = "ctl.hello";
pub const PEERS_REQUEST: &str = "ctl.peers.request";
pub const PEERS: &str = "ctl.peers";
pub const DIGEST_REQUEST: &str = "ctl.digest.request";
pub const DIGEST: &str = "ctl.digest";
pub const MESSAGES_REQUEST: &str = "ctl.messages.request";
pub const MESSAGES: &str = "ctl.messages";

pub const CAP_GOSSIP: &str = "gossip";
pub const CAP_DIGEST_SYNC: &str = "digest-sync";
pub const CAP_UDP: &str = "udp";

#[derive(Clone, Debug)]
pub struct HelloData {
    pub v: i64,
    pub impl_name: String,
    pub caps: Vec<String>,
    pub unknown_caps: Vec<String>,
    pub listen: Option<String>,
}

fn build(type_name: &str, data: JsonValue, ts: Option<i64>) -> Result<Envelope> {
    Envelope::build(type_name, data, ts)
}

/// §5.1. `caps` is sorted and deduplicated so an identical set is an identical message.
pub fn hello(
    impl_name: &str,
    caps: Option<&[&str]>,
    listen: Option<&str>,
    ts: Option<i64>,
) -> Result<Envelope> {
    let default = [CAP_GOSSIP, CAP_DIGEST_SYNC];
    let chosen = caps.unwrap_or(&default);
    let sorted: BTreeSet<&str> = chosen.iter().copied().collect();
    let caps_value = JsonValue::Array(
        sorted
            .into_iter()
            .map(|c| JsonValue::String(c.to_string()))
            .collect(),
    );
    let mut data = BTreeMap::new();
    data.insert("v".into(), JsonValue::Number(PROTOCOL_VERSION));
    data.insert("impl".into(), JsonValue::String(impl_name.into()));
    data.insert("caps".into(), caps_value);
    if let Some(listen) = listen {
        data.insert("listen".into(), JsonValue::String(listen.into()));
    }
    build(HELLO, JsonValue::Object(data), ts)
}

pub fn parse_hello(env: &Envelope) -> Result<HelloData> {
    if env.type_name != HELLO {
        return Err(Error::protocol(format!(
            "expected {HELLO}, got {}",
            env.type_name
        )));
    }
    let obj = env
        .data
        .as_object()
        .ok_or_else(|| Error::protocol("ctl.hello data must be an object"))?;

    let version = obj
        .get("v")
        .and_then(JsonValue::as_i64)
        .ok_or_else(|| Error::protocol("ctl.hello requires an integer v"))?;
    if version != PROTOCOL_VERSION {
        return Err(Error::protocol(format!(
            "peer speaks protocol v{version}, we speak v{PROTOCOL_VERSION}"
        )));
    }

    let impl_name = obj
        .get("impl")
        .and_then(JsonValue::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| Error::protocol("ctl.hello requires impl"))?
        .to_string();

    let caps = obj
        .get("caps")
        .and_then(JsonValue::as_array)
        .ok_or_else(|| Error::protocol("ctl.hello requires caps as an array of strings"))?;
    let mut known = Vec::new();
    let mut unknown = Vec::new();
    for cap in caps {
        let Some(name) = cap.as_str() else {
            return Err(Error::protocol(
                "ctl.hello requires caps as an array of strings",
            ));
        };
        if matches!(name, CAP_GOSSIP | CAP_DIGEST_SYNC | CAP_UDP) {
            known.push(name.to_string());
        } else {
            unknown.push(name.to_string());
        }
    }

    let listen = match obj.get("listen") {
        None => None,
        Some(JsonValue::String(s)) => Some(s.clone()),
        Some(_) => return Err(Error::protocol("ctl.hello listen must be a string")),
    };

    Ok(HelloData {
        v: version,
        impl_name,
        caps: known,
        unknown_caps: unknown,
        listen,
    })
}

pub fn peers_request(ts: Option<i64>) -> Result<Envelope> {
    build(PEERS_REQUEST, JsonValue::Object(BTreeMap::new()), ts)
}

pub fn peers(addresses: &[&str], ts: Option<i64>) -> Result<Envelope> {
    let list = JsonValue::Array(
        addresses
            .iter()
            .map(|a| JsonValue::String((*a).into()))
            .collect(),
    );
    build(PEERS, JsonValue::object([("peers".into(), list)]), ts)
}

pub fn digest_request(object_name: &str, ts: Option<i64>) -> Result<Envelope> {
    build(
        DIGEST_REQUEST,
        JsonValue::object([("object".into(), JsonValue::String(object_name.into()))]),
        ts,
    )
}

pub fn digest(
    object_name: &str,
    digest_hex: &str,
    frontier: &[&str],
    ts: Option<i64>,
) -> Result<Envelope> {
    build(
        DIGEST,
        JsonValue::object([
            ("object".into(), JsonValue::String(object_name.into())),
            ("digest".into(), JsonValue::String(digest_hex.into())),
            (
                "frontier".into(),
                JsonValue::Array(
                    frontier
                        .iter()
                        .map(|h| JsonValue::String((*h).into()))
                        .collect(),
                ),
            ),
        ]),
        ts,
    )
}

pub fn messages_request(object_name: &str, since: &str, ts: Option<i64>) -> Result<Envelope> {
    build(
        MESSAGES_REQUEST,
        JsonValue::object([
            ("object".into(), JsonValue::String(object_name.into())),
            ("since".into(), JsonValue::String(since.into())),
        ]),
        ts,
    )
}

pub fn messages(object_name: &str, envelopes: &[Envelope], ts: Option<i64>) -> Result<Envelope> {
    build(
        MESSAGES,
        JsonValue::object([
            ("object".into(), JsonValue::String(object_name.into())),
            (
                "messages".into(),
                JsonValue::Array(envelopes.iter().map(Envelope::to_object).collect()),
            ),
        ]),
        ts,
    )
}
