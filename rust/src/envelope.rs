//! Envelope — SPEC/wire-v1.md §3.

use std::collections::BTreeMap;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::canonical::{
    canonical_bytes, canonical_json, hex_to_bytes, parse_json, payload_digest, JsonValue,
};
use crate::crypto::{sign, verify, Algorithm};
use crate::error::{Error, Result};

pub const PROTOCOL_VERSION: i64 = 1;
pub const MAX_FUTURE_SKEW_MS: i64 = 300_000;

const TYPE_RE: &str = r"^[a-z0-9._-]{1,64}$";

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn is_type(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes.iter().all(|b| {
            b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'.' | b'_' | b'-')
        })
}

fn is_hex(value: &str, len: usize) -> bool {
    value.len() == len
        && value
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

#[derive(Clone, Debug)]
pub struct Envelope {
    pub v: i64,
    pub type_name: String,
    pub data: JsonValue,
    pub id: String,
    pub ts: i64,
    pub sig: Option<String>,
    pub pk: Option<String>,
    pub alg: Option<Algorithm>,
}

impl Envelope {
    pub fn build(type_name: &str, data: JsonValue, ts: Option<i64>) -> Result<Self> {
        if !is_type(type_name) {
            return Err(Error::protocol(format!("invalid type: {type_name:?}")));
        }
        let id = payload_digest(&data).map_err(|e| Error::protocol(e.to_string()))?;
        Ok(Self {
            v: PROTOCOL_VERSION,
            type_name: type_name.to_string(),
            data,
            id,
            ts: ts.unwrap_or_else(now_ms),
            sig: None,
            pk: None,
            alg: None,
        })
    }

    pub fn to_object(&self) -> JsonValue {
        let mut map = BTreeMap::new();
        map.insert("v".into(), JsonValue::Number(self.v));
        map.insert("type".into(), JsonValue::String(self.type_name.clone()));
        map.insert("data".into(), self.data.clone());
        map.insert("id".into(), JsonValue::String(self.id.clone()));
        map.insert("ts".into(), JsonValue::Number(self.ts));
        if let Some(sig) = &self.sig {
            map.insert("sig".into(), JsonValue::String(sig.clone()));
        }
        if let Some(pk) = &self.pk {
            map.insert("pk".into(), JsonValue::String(pk.clone()));
        }
        if let Some(alg) = self.alg {
            map.insert("alg".into(), JsonValue::String(alg.as_str().into()));
        }
        JsonValue::Object(map)
    }

    pub fn to_json(&self) -> Result<String> {
        canonical_json(&self.to_object()).map_err(|e| Error::protocol(e.to_string()))
    }

    pub fn to_bytes(&self) -> Result<Vec<u8>> {
        canonical_bytes(&self.to_object()).map_err(|e| Error::protocol(e.to_string()))
    }

    pub fn parse_text(text: &str, now_ms: Option<i64>) -> Result<Self> {
        let source = parse_json(text).map_err(|e| Error::protocol(e.to_string()))?;
        Self::from_value(&source, now_ms)
    }

    pub fn parse_bytes(raw: &[u8], now_ms: Option<i64>) -> Result<Self> {
        let text =
            std::str::from_utf8(raw).map_err(|_| Error::protocol("body is not valid UTF-8"))?;
        Self::parse_text(text, now_ms)
    }

    pub fn from_value(source: &JsonValue, clock: Option<i64>) -> Result<Self> {
        let obj = source
            .as_object()
            .ok_or_else(|| Error::protocol("envelope must be a JSON object"))?;

        const ALLOWED: &[&str] = &["v", "type", "data", "id", "ts", "sig", "pk", "alg"];
        let unknown: Vec<&String> = obj
            .keys()
            .filter(|k| !ALLOWED.contains(&k.as_str()))
            .collect();
        if !unknown.is_empty() {
            let mut names: Vec<&str> = unknown.iter().map(|s| s.as_str()).collect();
            names.sort();
            return Err(Error::protocol(format!(
                "unknown envelope fields: {names:?}"
            )));
        }
        for required in ["v", "type", "data", "id", "ts"] {
            if !obj.contains_key(required) {
                return Err(Error::protocol(format!(
                    "missing envelope fields: [\"{required}\"]"
                )));
            }
        }

        let version = obj
            .get("v")
            .and_then(JsonValue::as_i64)
            .ok_or_else(|| Error::protocol("v must be an integer"))?;
        if version != PROTOCOL_VERSION {
            return Err(Error::protocol(format!(
                "unsupported protocol version: {version}"
            )));
        }

        let type_name = obj
            .get("type")
            .and_then(JsonValue::as_str)
            .ok_or_else(|| Error::protocol("invalid type"))?;
        if !is_type(type_name) {
            return Err(Error::protocol(format!("invalid type: {type_name:?}")));
        }

        let ts = obj
            .get("ts")
            .and_then(JsonValue::as_i64)
            .ok_or_else(|| Error::protocol("ts must be an integer"))?;
        if ts < 0 {
            return Err(Error::protocol("ts must be non-negative"));
        }
        let reference = clock.unwrap_or_else(now_ms);
        if ts > reference + MAX_FUTURE_SKEW_MS {
            return Err(Error::protocol("ts is too far in the future"));
        }

        let id = obj
            .get("id")
            .and_then(JsonValue::as_str)
            .ok_or_else(|| Error::protocol("id must be 64 lowercase hex characters"))?;
        if !is_hex(id, 64) {
            return Err(Error::protocol("id must be 64 lowercase hex characters"));
        }

        let data = obj
            .get("data")
            .cloned()
            .ok_or_else(|| Error::protocol("missing envelope fields: [\"data\"]"))?;
        let computed = payload_digest(&data).map_err(|e| Error::protocol(e.to_string()))?;
        if computed != id {
            return Err(Error::protocol("id does not match the payload digest"));
        }

        let sig = obj.get("sig").and_then(JsonValue::as_str);
        let pk = obj.get("pk").and_then(JsonValue::as_str);
        let alg = obj.get("alg").and_then(JsonValue::as_str);

        let (sig, pk, alg) = if let Some(sig) = sig {
            if !is_hex(sig, 128) {
                return Err(Error::protocol("sig must be 128 lowercase hex characters"));
            }
            let pk = match pk {
                Some(p) if is_hex(p, 64) => p,
                _ => {
                    return Err(Error::protocol("pk must be 64 lowercase hex characters"));
                }
            };
            let alg = alg
                .and_then(Algorithm::parse)
                .ok_or_else(|| Error::protocol("alg must be one of [\"ed25519\",\"schnorr\"]"))?;
            (Some(sig.to_string()), Some(pk.to_string()), Some(alg))
        } else if pk.is_some() || alg.is_some() {
            return Err(Error::protocol("pk and alg require sig"));
        } else {
            (None, None, None)
        };

        Ok(Self {
            v: version,
            type_name: type_name.to_string(),
            data,
            id: id.to_string(),
            ts,
            sig,
            pk,
            alg,
        })
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>> {
        hex_to_bytes(&self.id).map_err(|e| Error::protocol(e.to_string()))
    }

    pub fn verify(&self) -> bool {
        let (Some(sig), Some(pk), Some(alg)) = (&self.sig, &self.pk, self.alg) else {
            return false;
        };
        let Ok(msg) = self.signing_bytes() else {
            return false;
        };
        let Ok(sig_bytes) = hex_to_bytes(sig) else {
            return false;
        };
        let Ok(pk_bytes) = hex_to_bytes(pk) else {
            return false;
        };
        verify(alg.as_str(), &msg, &sig_bytes, &pk_bytes)
    }

    pub fn signed(&self, alg: Algorithm, secret_key: &[u8], aux: Option<&[u8]>) -> Result<Self> {
        let msg = self.signing_bytes()?;
        let result = sign(alg, &msg, secret_key, aux).map_err(Error::protocol)?;
        Ok(Self {
            v: self.v,
            type_name: self.type_name.clone(),
            data: self.data.clone(),
            id: self.id.clone(),
            ts: self.ts,
            sig: Some(hex::encode(result.signature)),
            pk: Some(hex::encode(result.public_key)),
            alg: Some(alg),
        })
    }

    pub fn path(&self) -> &'static str {
        if self.type_name.starts_with("ctl.") || self.type_name.starts_with("link.") {
            "control"
        } else {
            "gossip"
        }
    }

    pub fn is_control(&self) -> bool {
        self.path() == "control"
    }
}

// Silence unused TYPE_RE — the check is handwritten so we stay allocation-light.
#[allow(dead_code)]
fn _type_re_docs() -> &'static str {
    TYPE_RE
}
