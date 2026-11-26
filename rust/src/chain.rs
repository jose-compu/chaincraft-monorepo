//! Transfer chain — SPEC/features/chain-transfer.md.

use std::collections::BTreeMap;

use sha2::{Digest, Sha256};

use crate::canonical::{canonical_bytes, JsonValue, MAX_SAFE_INT};
use crate::crypto::{self, Algorithm};
use crate::object::merkle_digest;

fn is_int(value: &JsonValue) -> Option<i64> {
    value.as_i64()
}

fn is_hex64(text: &str) -> bool {
    text.len() == 64 && text.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

fn is_sig128(text: &str) -> bool {
    text.len() == 128 && text.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

pub fn normalize_genesis(genesis: &BTreeMap<String, i64>) -> Result<BTreeMap<String, i64>, String> {
    if genesis.is_empty() {
        return Err("genesis must not be empty".into());
    }
    let mut out = BTreeMap::new();
    for (account, amount) in genesis {
        if account.is_empty() {
            return Err("account id must be non-empty".into());
        }
        if *amount < 1 || *amount > MAX_SAFE_INT {
            return Err("each balance must be an integer in 1..2^53-1".into());
        }
        out.insert(account.clone(), *amount);
    }
    Ok(out)
}

pub fn transaction_id(body: &JsonValue) -> Result<String, String> {
    merkle_digest(body).map_err(|e| e.to_string())
}

pub fn transfer_signing_bytes(body: &JsonValue) -> Result<Vec<u8>, String> {
    let bytes = canonical_bytes(body).map_err(|err| format!("{err:?}"))?;
    Ok(Sha256::digest(&bytes).to_vec())
}

fn parse_body(body: &JsonValue) -> Option<BTreeMap<String, JsonValue>> {
    let obj = body.as_object()?;
    let amount = is_int(obj.get("amount")?)?;
    let fee = is_int(obj.get("fee")?)?;
    let nonce = is_int(obj.get("nonce")?)?;
    let recipient = obj.get("recipient")?.as_str()?;
    let sender = obj.get("sender")?.as_str()?;
    if amount < 1 || fee < 0 || nonce < 0 || recipient.is_empty() || !is_hex64(sender) {
        return None;
    }
    let mut out = BTreeMap::new();
    out.insert("amount".into(), JsonValue::Number(amount));
    out.insert("fee".into(), JsonValue::Number(fee));
    out.insert("nonce".into(), JsonValue::Number(nonce));
    out.insert("recipient".into(), JsonValue::String(recipient.to_owned()));
    out.insert("sender".into(), JsonValue::String(sender.to_owned()));
    Some(out)
}

pub fn verify_transfer(tx: &JsonValue) -> bool {
    let obj = match tx.as_object() {
        Some(o) => o,
        None => return false,
    };
    let signature = match obj.get("signature").and_then(JsonValue::as_str) {
        Some(s) if is_sig128(s) => s,
        _ => return false,
    };
    let mut body_pairs = BTreeMap::new();
    for (key, value) in obj {
        if key != "signature" {
            body_pairs.insert(key.clone(), value.clone());
        }
    }
    let body = JsonValue::Object(body_pairs);
    let parsed = match parse_body(&body) {
        Some(p) => JsonValue::Object(p),
        None => return false,
    };
    let signing = match transfer_signing_bytes(&parsed) {
        Ok(b) => b,
        Err(_) => return false,
    };
    let sig_bytes = match hex::decode(signature) {
        Ok(b) if b.len() == 64 => b,
        _ => return false,
    };
    let pk_bytes = match hex::decode(
        parsed
            .as_object()
            .unwrap()
            .get("sender")
            .unwrap()
            .as_str()
            .unwrap(),
    ) {
        Ok(b) if b.len() == 32 => b,
        _ => return false,
    };
    crypto::verify(crypto::SCHNORR, &signing, &sig_bytes, &pk_bytes)
}

pub fn sign_transfer(
    body: &JsonValue,
    secret_key: &[u8],
    aux: Option<&[u8]>,
) -> Result<JsonValue, String> {
    let parsed = parse_body(body).ok_or_else(|| "invalid transfer body".to_string())?;
    let body_value = JsonValue::Object(parsed.clone());
    let signing = transfer_signing_bytes(&body_value)?;
    let result =
        crypto::sign(Algorithm::Schnorr, &signing, secret_key, aux).map_err(|e| e.to_string())?;
    let mut out = parsed;
    out.insert(
        "signature".into(),
        JsonValue::String(hex::encode(result.signature)),
    );
    Ok(JsonValue::Object(out))
}

pub fn block_id(header: &JsonValue) -> Result<String, String> {
    merkle_digest(header).map_err(|e| e.to_string())
}

struct ChainMempool {
    txs: BTreeMap<String, JsonValue>,
}

impl ChainMempool {
    fn new() -> Self {
        Self {
            txs: BTreeMap::new(),
        }
    }

    fn submit(&mut self, tx: JsonValue) -> bool {
        if !verify_transfer(&tx) {
            return false;
        }
        let obj = tx.as_object().expect("valid tx");
        let mut body_pairs = BTreeMap::new();
        for (key, value) in obj {
            if key != "signature" {
                body_pairs.insert(key.clone(), value.clone());
            }
        }
        let body = JsonValue::Object(body_pairs);
        let tid = transaction_id(&body).expect("valid");
        self.txs.insert(tid, tx);
        true
    }

    fn ordered(&self) -> Vec<JsonValue> {
        let mut items: Vec<JsonValue> = self.txs.values().cloned().collect();
        items.sort_by(|a, b| {
            let body_a = tx_body(a);
            let body_b = tx_body(b);
            let fee_a = field(&body_a, "fee")
                .and_then(JsonValue::as_i64)
                .unwrap_or(0);
            let fee_b = field(&body_b, "fee")
                .and_then(JsonValue::as_i64)
                .unwrap_or(0);
            let tid_a = transaction_id(&body_a).unwrap_or_default();
            let tid_b = transaction_id(&body_b).unwrap_or_default();
            fee_b.cmp(&fee_a).then_with(|| tid_a.cmp(&tid_b))
        });
        items
    }

    fn remove(&mut self, ids: &[String]) {
        for tid in ids {
            self.txs.remove(tid);
        }
    }
}

fn apply_tx(
    reward: i64,
    _genesis: &BTreeMap<String, i64>,
    tx: &JsonValue,
    producer: &str,
    balances: &mut BTreeMap<String, i64>,
    nonces: &mut BTreeMap<String, i64>,
) -> bool {
    if !verify_transfer(tx) {
        return false;
    }
    let body = tx_body(tx);
    let obj = body.as_object().unwrap();
    let sender = obj.get("sender").unwrap().as_str().unwrap();
    let recipient = obj.get("recipient").unwrap().as_str().unwrap();
    let amount = obj.get("amount").unwrap().as_i64().unwrap();
    let fee = obj.get("fee").unwrap().as_i64().unwrap();
    let nonce = obj.get("nonce").unwrap().as_i64().unwrap();
    if nonce != *nonces.get(sender).unwrap_or(&0) {
        return false;
    }
    let sender_bal = *balances.get(sender).unwrap_or(&0);
    if sender_bal < amount + fee {
        return false;
    }
    if balances.get(recipient).unwrap_or(&0) + amount > MAX_SAFE_INT {
        return false;
    }
    let producer_credit = fee + reward;
    if balances.get(producer).unwrap_or(&0) + producer_credit > MAX_SAFE_INT {
        return false;
    }
    balances.insert(sender.to_owned(), sender_bal - amount - fee);
    balances.insert(
        recipient.to_owned(),
        balances.get(recipient).unwrap_or(&0) + amount,
    );
    balances.insert(
        producer.to_owned(),
        balances.get(producer).unwrap_or(&0) + producer_credit,
    );
    nonces.insert(sender.to_owned(), nonce + 1);
    nonces.entry(recipient.to_owned()).or_insert(0);
    nonces.entry(producer.to_owned()).or_insert(0);
    true
}

fn field<'a>(value: &'a JsonValue, key: &str) -> Option<&'a JsonValue> {
    value.as_object()?.get(key)
}

fn tx_body(tx: &JsonValue) -> JsonValue {
    let obj = tx.as_object().unwrap();
    let mut body_pairs = BTreeMap::new();
    for (key, value) in obj {
        if key != "signature" {
            body_pairs.insert(key.clone(), value.clone());
        }
    }
    JsonValue::Object(body_pairs)
}

pub trait ChainDriver: Send {
    fn build_proof(&mut self, block: &JsonValue) -> Result<JsonValue, String>;
    fn authorize(&mut self, block: &JsonValue, proof: &JsonValue) -> bool;
    fn canonical(&self) -> Vec<String>;
}

pub struct TransferChain {
    genesis: BTreeMap<String, i64>,
    reward: i64,
    driver: Option<Box<dyn ChainDriver>>,
    blocks: BTreeMap<String, JsonValue>,
    mempool: ChainMempool,
    balances: BTreeMap<String, i64>,
    nonces: BTreeMap<String, i64>,
    canonical: Vec<String>,
    height: i64,
    tip: String,
}

impl TransferChain {
    pub fn new(
        genesis: BTreeMap<String, i64>,
        reward: i64,
        driver: Option<Box<dyn ChainDriver>>,
    ) -> Result<Self, String> {
        if reward < 0 {
            return Err("reward must be >= 0".into());
        }
        let genesis = normalize_genesis(&genesis)?;
        let balances = genesis.clone();
        let nonces = genesis.keys().cloned().map(|k| (k, 0)).collect();
        Ok(Self {
            genesis,
            reward,
            driver,
            blocks: BTreeMap::new(),
            mempool: ChainMempool::new(),
            balances,
            nonces,
            canonical: Vec::new(),
            height: 0,
            tip: String::new(),
        })
    }

    pub fn set_driver(&mut self, driver: Box<dyn ChainDriver>) {
        self.driver = Some(driver);
    }

    pub fn submit(&mut self, tx: &JsonValue) -> bool {
        if tx.as_object().is_none() {
            return false;
        }
        self.mempool.submit(tx.clone())
    }

    fn tx_root(&self, txs: &[JsonValue]) -> Result<String, String> {
        let mut ids = Vec::new();
        for tx in txs {
            let body = tx_body(tx);
            ids.push(transaction_id(&body)?);
        }
        merkle_digest(&JsonValue::Array(
            ids.into_iter().map(JsonValue::String).collect(),
        ))
        .map_err(|e| e.to_string())
    }

    fn apply_tx(
        &self,
        tx: &JsonValue,
        producer: &str,
        balances: &mut BTreeMap<String, i64>,
        nonces: &mut BTreeMap<String, i64>,
    ) -> bool {
        apply_tx(self.reward, &self.genesis, tx, producer, balances, nonces)
    }

    fn apply_block_transactions(
        &self,
        txs: &[JsonValue],
        producer: &str,
        balances: &mut BTreeMap<String, i64>,
        nonces: &mut BTreeMap<String, i64>,
    ) -> bool {
        for tx in txs {
            if !apply_tx(self.reward, &self.genesis, tx, producer, balances, nonces) {
                return false;
            }
        }
        true
    }

    fn replay_canonical(&mut self, canon: &[String]) {
        self.balances = self.genesis.clone();
        self.nonces = self.genesis.keys().cloned().map(|k| (k, 0)).collect();
        self.canonical.clear();
        self.height = 0;
        self.tip.clear();
        for bid in canon {
            let block = match self.blocks.get(bid) {
                Some(b) => b.clone(),
                None => return,
            };
            let header = block
                .as_object()
                .and_then(|o| o.get("header"))
                .expect("header");
            let txs = block
                .as_object()
                .and_then(|o| o.get("transactions"))
                .and_then(JsonValue::as_array)
                .map(|items| items.to_vec())
                .unwrap_or_default();
            let producer = header
                .as_object()
                .and_then(|h| h.get("producer"))
                .and_then(JsonValue::as_str)
                .expect("producer");
            let reward = self.reward;
            for tx in &txs {
                if !apply_tx(
                    reward,
                    &self.genesis,
                    tx,
                    producer,
                    &mut self.balances,
                    &mut self.nonces,
                ) {
                    return;
                }
            }
            self.canonical.push(bid.to_owned());
            self.height = header
                .as_object()
                .unwrap()
                .get("height")
                .unwrap()
                .as_i64()
                .unwrap();
            self.tip = bid.to_owned();
        }
    }

    fn validate_header(&self, header: &JsonValue, parent_id: &str) -> bool {
        let obj = match header.as_object() {
            Some(o) => o,
            None => return false,
        };
        let height = match obj.get("height").and_then(is_int) {
            Some(h) if h >= 1 => h,
            _ => return false,
        };
        let parent = match obj.get("parent").and_then(JsonValue::as_str) {
            Some(p) => p,
            None => return false,
        };
        let producer = match obj.get("producer").and_then(JsonValue::as_str) {
            Some(p) if !p.is_empty() => p,
            _ => return false,
        };
        let state_root = match obj.get("state_root").and_then(JsonValue::as_str) {
            Some(s) if is_hex64(s) => s,
            _ => return false,
        };
        let time = match obj.get("time").and_then(is_int) {
            Some(t) if t >= 0 => t,
            _ => return false,
        };
        let tx_root = match obj.get("tx_root").and_then(JsonValue::as_str) {
            Some(s) if is_hex64(s) => s,
            _ => return false,
        };
        let _ = (producer, state_root, time, tx_root);
        if height == 1 {
            parent.is_empty()
        } else {
            parent == parent_id && self.blocks.contains_key(parent_id)
        }
    }

    fn validate_block_record(&mut self, block: &JsonValue, check_driver: bool) -> bool {
        let obj = match block.as_object() {
            Some(o) => o,
            None => return false,
        };
        if obj.get("chain").and_then(JsonValue::as_str) != Some("transfer") {
            return false;
        }
        let header = obj.get("header");
        let txs = obj.get("transactions");
        if !txs.and_then(JsonValue::as_array).is_some() {
            return false;
        }
        let parent_id = if let Some(hdr) = header.and_then(JsonValue::as_object) {
            if hdr.get("height").and_then(JsonValue::as_i64).unwrap_or(0) > 1 {
                hdr.get("parent").and_then(JsonValue::as_str).unwrap_or("")
            } else {
                ""
            }
        } else {
            ""
        };
        let header = match header {
            Some(h) if self.validate_header(h, parent_id) => h,
            _ => return false,
        };
        let bid = match block_id(header) {
            Ok(id) => id,
            Err(_) => return false,
        };
        if self.blocks.contains_key(&bid) {
            return false;
        }
        let txs = txs.and_then(JsonValue::as_array).unwrap();
        for tx in txs {
            if !verify_transfer(tx) {
                return false;
            }
        }
        if self.tx_root(txs).ok().as_deref()
            != header
                .as_object()
                .unwrap()
                .get("tx_root")
                .and_then(JsonValue::as_str)
        {
            return false;
        }
        let mut balances = self.genesis.clone();
        let mut nonces: BTreeMap<String, i64> =
            self.genesis.keys().cloned().map(|k| (k, 0)).collect();
        let hdr = header.as_object().unwrap();
        if hdr.get("height").unwrap().as_i64().unwrap() > 1 {
            let parent = hdr.get("parent").unwrap().as_str().unwrap();
            let chain_prefix = self.canonical_for_parent(parent);
            for pid in &chain_prefix {
                let pb = self.blocks.get(pid).unwrap();
                let ptxs = pb
                    .as_object()
                    .and_then(|o| o.get("transactions"))
                    .and_then(JsonValue::as_array)
                    .map(|items| items.to_vec())
                    .unwrap_or_default();
                let pprod = pb
                    .as_object()
                    .and_then(|o| o.get("header"))
                    .and_then(JsonValue::as_object)
                    .and_then(|h| h.get("producer"))
                    .and_then(JsonValue::as_str)
                    .unwrap();
                if !self.apply_block_transactions(&ptxs, pprod, &mut balances, &mut nonces) {
                    return false;
                }
            }
        }
        let producer = hdr.get("producer").unwrap().as_str().unwrap();
        if !self.apply_block_transactions(txs, producer, &mut balances, &mut nonces) {
            return false;
        }
        let snap = JsonValue::object([
            (
                "balances".into(),
                JsonValue::object(
                    balances
                        .iter()
                        .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                ),
            ),
            (
                "nonces".into(),
                JsonValue::object(
                    nonces
                        .iter()
                        .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                ),
            ),
            ("v".into(), JsonValue::Number(1)),
        ]);
        if merkle_digest(&snap).ok().as_deref() != hdr.get("state_root").and_then(JsonValue::as_str)
        {
            return false;
        }
        if check_driver {
            if let Some(driver) = &mut self.driver {
                let empty = JsonValue::Object(BTreeMap::new());
                let proof = obj.get("proof").unwrap_or(&empty);
                if !driver.authorize(block, proof) {
                    return false;
                }
            }
        }
        true
    }

    fn canonical_for_parent(&self, parent_id: &str) -> Vec<String> {
        if parent_id.is_empty() {
            return Vec::new();
        }
        if let Some(driver) = &self.driver {
            let canon = driver.canonical();
            if let Some(idx) = canon.iter().position(|id| id == parent_id) {
                return canon[..=idx].to_vec();
            }
        }
        let mut chain = Vec::new();
        let mut cursor = parent_id.to_owned();
        while !cursor.is_empty() {
            chain.push(cursor.clone());
            let block = match self.blocks.get(&cursor) {
                Some(b) => b,
                None => break,
            };
            cursor = block
                .as_object()
                .and_then(|o| o.get("header"))
                .and_then(JsonValue::as_object)
                .and_then(|h| h.get("parent"))
                .and_then(JsonValue::as_str)
                .unwrap_or("")
                .to_owned();
        }
        chain.reverse();
        chain
    }

    pub fn accept_block(&mut self, block: &JsonValue) -> bool {
        if block.as_object().is_none() {
            return false;
        }
        if !self.validate_block_record(block, true) {
            return false;
        }
        let header = block.as_object().unwrap().get("header").unwrap();
        let bid = block_id(header).expect("valid");
        self.blocks.insert(bid.clone(), block.clone());
        if self.driver.is_some() {
            let canon = self.driver.as_ref().unwrap().canonical();
            self.replay_canonical(&canon);
        } else {
            let canon = self.extend_canonical(&bid);
            self.replay_canonical(&canon);
        }
        true
    }

    fn extend_canonical(&self, bid: &str) -> Vec<String> {
        let mut chain = Vec::new();
        let mut cursor = bid.to_owned();
        while !cursor.is_empty() {
            chain.push(cursor.clone());
            let block = match self.blocks.get(&cursor) {
                Some(b) => b,
                None => break,
            };
            cursor = block
                .as_object()
                .and_then(|o| o.get("header"))
                .and_then(JsonValue::as_object)
                .and_then(|h| h.get("parent"))
                .and_then(JsonValue::as_str)
                .unwrap_or("")
                .to_owned();
        }
        chain.reverse();
        chain
    }

    pub fn produce(&mut self, time: i64, producer: &str) -> Result<Option<JsonValue>, String> {
        if time < 0 {
            return Err("time must be >= 0".into());
        }
        if producer.is_empty() {
            return Err("producer required".into());
        }
        let parent = self.tip.clone();
        let height = self.height + 1;
        let mut balances = self.balances.clone();
        let mut nonces = self.nonces.clone();
        let mut included = Vec::new();
        let mut included_ids = Vec::new();
        for tx in self.mempool.ordered() {
            let body = tx_body(&tx);
            let tid = transaction_id(&body)?;
            let mut trial_bal = balances.clone();
            let mut trial_non = nonces.clone();
            if self.apply_tx(&tx, producer, &mut trial_bal, &mut trial_non) {
                included.push(tx.clone());
                included_ids.push(tid);
                balances = trial_bal;
                nonces = trial_non;
            } else {
                break;
            }
        }
        let snap = JsonValue::object([
            (
                "balances".into(),
                JsonValue::object(
                    balances
                        .iter()
                        .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                ),
            ),
            (
                "nonces".into(),
                JsonValue::object(
                    nonces
                        .iter()
                        .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                ),
            ),
            ("v".into(), JsonValue::Number(1)),
        ]);
        let header = JsonValue::object([
            ("height".into(), JsonValue::Number(height)),
            ("parent".into(), JsonValue::String(parent)),
            ("producer".into(), JsonValue::String(producer.to_owned())),
            (
                "state_root".into(),
                JsonValue::String(merkle_digest(&snap).map_err(|e| e.to_string())?),
            ),
            ("time".into(), JsonValue::Number(time)),
            (
                "tx_root".into(),
                JsonValue::String(self.tx_root(&included)?),
            ),
        ]);
        let mut block = JsonValue::object([
            ("chain".into(), JsonValue::String("transfer".into())),
            ("header".into(), header.clone()),
            ("transactions".into(), JsonValue::Array(included.clone())),
            ("proof".into(), JsonValue::Object(BTreeMap::new())),
        ]);
        if let Some(driver) = &mut self.driver {
            let proof = driver.build_proof(&block)?;
            if let JsonValue::Object(ref mut obj) = block {
                obj.insert("proof".into(), proof);
            }
        }
        if !self.accept_block(&block) {
            return Ok(None);
        }
        self.mempool.remove(&included_ids);
        Ok(Some(block))
    }

    pub fn import_blocks(&mut self, blocks: &[JsonValue]) -> bool {
        for block in blocks {
            if !self.accept_block(block) {
                return false;
            }
        }
        true
    }

    pub fn state(&self) -> JsonValue {
        JsonValue::object([
            (
                "balances".into(),
                JsonValue::object(
                    self.balances
                        .iter()
                        .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                ),
            ),
            (
                "nonces".into(),
                JsonValue::object(
                    self.nonces
                        .iter()
                        .map(|(k, v)| (k.clone(), JsonValue::Number(*v))),
                ),
            ),
            (
                "canonical".into(),
                JsonValue::Array(
                    self.canonical
                        .iter()
                        .cloned()
                        .map(JsonValue::String)
                        .collect(),
                ),
            ),
            ("height".into(), JsonValue::Number(self.height)),
            ("tip".into(), JsonValue::String(self.tip.clone())),
        ])
    }
}
