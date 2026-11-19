//! Proof-of-transfer object — SPEC/features/consensus-pox.md.

use std::any::Any;
use std::collections::{BTreeMap, HashMap, HashSet};

use crate::canonical::JsonValue;
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};

const MAX_INT: i64 = 9007199254740991;

#[derive(Clone, Debug)]
struct Stacker {
    locker: String,
    amount: i64,
}

#[derive(Clone, Debug)]
struct StackRecord {
    locker: String,
    amount: i64,
    reward_cycle: i64,
}

#[derive(Clone, Debug)]
struct BidRecord {
    miner: String,
    btc_out: i64,
    block_height: i64,
}

#[derive(Clone, Debug)]
struct TenureRecord {
    winner: String,
    prev: String,
    block_height: i64,
}

enum Parsed {
    Stack(String, StackRecord),
    Bid(String, BidRecord),
    Tenure(String, TenureRecord),
}

#[derive(Debug)]
pub struct ProofOfTransfer {
    seed: String,
    cycle_length: i64,
    snapshot0: Vec<Stacker>,
    stacks: HashMap<String, StackRecord>,
    stack_order: Vec<String>,
    stacks_by_cycle: HashMap<i64, HashSet<String>>,
    bids: HashMap<String, BidRecord>,
    bid_order: Vec<String>,
    bids_by_height: HashMap<i64, HashMap<String, String>>,
    tenures: HashMap<String, TenureRecord>,
    tenure_order: Vec<String>,
    open_height: i64,
}

fn is_seed(seed: &str) -> bool {
    seed.len() == 64 && seed.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

fn is_wire_int(value: &JsonValue) -> Option<i64> {
    match value {
        JsonValue::Number(n) if (0..=MAX_INT).contains(n) => Some(*n),
        _ => None,
    }
}

pub fn reward_cycle(height: i64, cycle_length: i64) -> i64 {
    if height < 1 {
        0
    } else {
        (height - 1) / cycle_length
    }
}

pub fn stack_id(locker: &str, amount: i64, reward_cycle: i64) -> String {
    let payload = JsonValue::object([
        ("amount".into(), JsonValue::Number(amount)),
        ("kind".into(), JsonValue::String("stack".into())),
        ("locker".into(), JsonValue::String(locker.to_owned())),
        ("reward_cycle".into(), JsonValue::Number(reward_cycle)),
    ]);
    merkle_digest(&payload).expect("canonical")
}

pub fn bid_id(miner: &str, btc_out: i64, block_height: i64) -> String {
    let payload = JsonValue::object([
        ("block_height".into(), JsonValue::Number(block_height)),
        ("btc_out".into(), JsonValue::Number(btc_out)),
        ("kind".into(), JsonValue::String("bid".into())),
        ("miner".into(), JsonValue::String(miner.to_owned())),
    ]);
    merkle_digest(&payload).expect("canonical")
}

pub fn tenure_id(winner: &str, prev: &str, block_height: i64) -> String {
    let payload = JsonValue::object([
        ("block_height".into(), JsonValue::Number(block_height)),
        ("kind".into(), JsonValue::String("tenure".into())),
        ("prev".into(), JsonValue::String(prev.to_owned())),
        ("winner".into(), JsonValue::String(winner.to_owned())),
    ]);
    merkle_digest(&payload).expect("canonical")
}

pub fn sortition_score(seed: &str, miner: &str, btc_out: i64, block_height: i64) -> String {
    let payload = JsonValue::object([
        ("block_height".into(), JsonValue::Number(block_height)),
        ("btc_out".into(), JsonValue::Number(btc_out)),
        ("miner".into(), JsonValue::String(miner.to_owned())),
        ("seed".into(), JsonValue::String(seed.to_owned())),
    ]);
    merkle_digest(&payload).expect("canonical")
}

impl ProofOfTransfer {
    pub fn new(
        seed: &str,
        cycle_length: i64,
        stackers: &[(String, i64)],
    ) -> Result<Self, String> {
        if !is_seed(seed) {
            return Err("seed must be 64 lowercase hex characters".into());
        }
        if !(1..=MAX_INT).contains(&cycle_length) {
            return Err("cycle_length must be an integer >= 1".into());
        }
        if stackers.is_empty() {
            return Err("stackers must be non-empty".into());
        }
        let mut seen = HashSet::new();
        let mut snapshot0 = Vec::new();
        for (locker, amount) in stackers {
            if locker.is_empty() {
                return Err("each locker must be a non-empty string".into());
            }
            if !(1..=MAX_INT).contains(amount) {
                return Err("each amount must be an integer >= 1".into());
            }
            if !seen.insert(locker.clone()) {
                return Err("lockers must be distinct".into());
            }
            snapshot0.push(Stacker {
                locker: locker.clone(),
                amount: *amount,
            });
        }
        Ok(Self {
            seed: seed.to_owned(),
            cycle_length,
            snapshot0,
            stacks: HashMap::new(),
            stack_order: Vec::new(),
            stacks_by_cycle: HashMap::new(),
            bids: HashMap::new(),
            bid_order: Vec::new(),
            bids_by_height: HashMap::new(),
            tenures: HashMap::new(),
            tenure_order: Vec::new(),
            open_height: 1,
        })
    }

    pub fn state(
        &self,
    ) -> (
        i64,
        String,
        i64,
        i64,
        Vec<String>,
        Vec<String>,
        Vec<String>,
        Vec<String>,
    ) {
        let (tip, height) = self.tip();
        let open_height = self.open_height;
        let canonical = self.canonical(&tip);
        (
            height,
            tip,
            open_height,
            reward_cycle(open_height, self.cycle_length),
            canonical,
            self.tenure_order.clone(),
            self.bid_order.clone(),
            self.stack_order.clone(),
        )
    }

    fn tip(&self) -> (String, i64) {
        let mut best = String::new();
        let mut best_height = 0;
        for (digest, record) in &self.tenures {
            if record.block_height > best_height
                || (record.block_height == best_height && (best.is_empty() || digest < &best))
            {
                best = digest.clone();
                best_height = record.block_height;
            }
        }
        (best, best_height)
    }

    fn canonical(&self, tip: &str) -> Vec<String> {
        let mut chain = Vec::new();
        let mut cursor = tip.to_owned();
        while !cursor.is_empty() {
            let prev = self.tenures[&cursor].prev.clone();
            chain.push(cursor);
            cursor = prev;
        }
        chain.reverse();
        chain
    }

    fn snapshot_lockers(&self, cycle: i64) -> HashSet<String> {
        if cycle == 0 {
            return self.snapshot0.iter().map(|s| s.locker.clone()).collect();
        }
        let mut lockers = HashSet::new();
        for digest in &self.stack_order {
            let record = &self.stacks[digest];
            if record.reward_cycle == cycle {
                lockers.insert(record.locker.clone());
            }
        }
        lockers
    }

    fn elected_miner(&self, block_height: i64) -> Option<String> {
        let miners = self.bids_by_height.get(&block_height)?;
        if miners.is_empty() {
            return None;
        }
        let mut best_miner: Option<String> = None;
        let mut best_score = String::new();
        let mut best_id = String::new();
        for (miner, digest) in miners {
            let record = &self.bids[digest];
            let score = sortition_score(
                &self.seed,
                miner,
                record.btc_out,
                block_height,
            );
            if best_miner.is_none()
                || score < best_score
                || (score == best_score && digest < &best_id)
            {
                best_miner = Some(miner.clone());
                best_score = score;
                best_id = digest.clone();
            }
        }
        best_miner
    }

    fn contains_id(&self, digest: &str) -> bool {
        self.stacks.contains_key(digest)
            || self.bids.contains_key(digest)
            || self.tenures.contains_key(digest)
    }

    fn parse(&self, message: &JsonValue) -> Option<Parsed> {
        let obj = message.as_object()?;
        if obj.get("consensus").and_then(JsonValue::as_str) != Some("pox") {
            return None;
        }
        match obj.get("kind").and_then(JsonValue::as_str)? {
            "stack" => self.parse_stack(obj),
            "bid" => self.parse_bid(obj),
            "tenure" => self.parse_tenure(obj),
            _ => None,
        }
    }

    fn parse_stack(&self, obj: &BTreeMap<String, JsonValue>) -> Option<Parsed> {
        let locker = obj.get("locker").and_then(JsonValue::as_str)?;
        let amount = is_wire_int(obj.get("amount")?)?;
        let reward_cycle_val = is_wire_int(obj.get("reward_cycle")?)?;
        if locker.is_empty() || amount < 1 || reward_cycle_val < 1 {
            return None;
        }
        let open_cycle = reward_cycle(self.open_height, self.cycle_length);
        if reward_cycle_val <= open_cycle {
            return None;
        }
        if self
            .stacks_by_cycle
            .get(&reward_cycle_val)
            .is_some_and(|set| set.contains(locker))
        {
            return None;
        }
        let digest = stack_id(locker, amount, reward_cycle_val);
        if self.contains_id(&digest) {
            return None;
        }
        Some(Parsed::Stack(
            digest,
            StackRecord {
                locker: locker.to_owned(),
                amount,
                reward_cycle: reward_cycle_val,
            },
        ))
    }

    fn parse_bid(&self, obj: &BTreeMap<String, JsonValue>) -> Option<Parsed> {
        let miner = obj.get("miner").and_then(JsonValue::as_str)?;
        let btc_out = is_wire_int(obj.get("btc_out")?)?;
        let block_height = is_wire_int(obj.get("block_height")?)?;
        if miner.is_empty() || btc_out < 1 || block_height != self.open_height {
            return None;
        }
        let cycle = reward_cycle(block_height, self.cycle_length);
        if !self.snapshot_lockers(cycle).contains(miner) {
            return None;
        }
        if self
            .bids_by_height
            .get(&block_height)
            .is_some_and(|m| m.contains_key(miner))
        {
            return None;
        }
        let digest = bid_id(miner, btc_out, block_height);
        if self.contains_id(&digest) {
            return None;
        }
        Some(Parsed::Bid(
            digest,
            BidRecord {
                miner: miner.to_owned(),
                btc_out,
                block_height,
            },
        ))
    }

    fn parse_tenure(&self, obj: &BTreeMap<String, JsonValue>) -> Option<Parsed> {
        let winner = obj.get("winner").and_then(JsonValue::as_str)?;
        let prev = obj.get("prev").and_then(JsonValue::as_str)?;
        let block_height = is_wire_int(obj.get("block_height")?)?;
        if winner.is_empty() || block_height != self.open_height {
            return None;
        }
        let elected = self.elected_miner(block_height)?;
        if winner != elected {
            return None;
        }
        let (tip, _) = self.tip();
        if block_height == 1 {
            if !prev.is_empty() {
                return None;
            }
        } else if prev != tip {
            return None;
        }
        let digest = tenure_id(winner, prev, block_height);
        if self.contains_id(&digest) {
            return None;
        }
        Some(Parsed::Tenure(
            digest,
            TenureRecord {
                winner: winner.to_owned(),
                prev: prev.to_owned(),
                block_height,
            },
        ))
    }
}

impl ApplicationObject for ProofOfTransfer {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn is_valid(&self, message: &JsonValue) -> bool {
        self.parse(message).is_some()
    }

    fn add_message(
        &mut self,
        message: &JsonValue,
        _frontier_state: Option<&StateMemento>,
    ) -> Option<StateMemento> {
        let Some(parsed) = self.parse(message) else {
            return Some(self.emit_state_memento());
        };
        match parsed {
            Parsed::Stack(digest, record) => {
                self.stacks.insert(digest.clone(), record.clone());
                self.stack_order.push(digest);
                self.stacks_by_cycle
                    .entry(record.reward_cycle)
                    .or_default()
                    .insert(record.locker);
            }
            Parsed::Bid(digest, record) => {
                let miner = record.miner.clone();
                let height = record.block_height;
                self.bids.insert(digest.clone(), record);
                self.bid_order.push(digest.clone());
                self.bids_by_height
                    .entry(height)
                    .or_default()
                    .insert(miner, digest);
            }
            Parsed::Tenure(digest, record) => {
                self.open_height = record.block_height + 1;
                self.tenures.insert(digest.clone(), record);
                self.tenure_order.push(digest);
            }
        }
        Some(self.emit_state_memento())
    }

    fn emit_state_memento(&self) -> StateMemento {
        let (tip, height) = self.tip();
        let payload = JsonValue::object([
            ("height".into(), JsonValue::Number(height)),
            ("tip".into(), JsonValue::String(tip)),
            ("v".into(), JsonValue::Number(1)),
        ]);
        let digest = merkle_digest(&payload).expect("canonical");
        StateMemento::normalize(&digest, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        let (tip, _) = self.tip();
        if tip.is_empty() {
            Vec::new()
        } else {
            vec![tip]
        }
    }

    fn is_merkelized(&self) -> bool {
        true
    }
}