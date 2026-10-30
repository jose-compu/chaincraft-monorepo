//! Slush, Snowflake, and Snowball — SPEC/features/consensus-avalanche.md.

use std::any::Any;

use crate::canonical::JsonValue;
use crate::memento::StateMemento;
use crate::object::{merkle_digest, ApplicationObject};

pub const PHASES: &[&str] = &["slush", "snowflake", "snowball"];
pub const COLORS: &[&str] = &["blue", "red"];
pub const DEFAULT_K: usize = 2;
pub const DEFAULT_ALPHA: usize = 2;
pub const DEFAULT_BETA: usize = 2;

pub struct Avalanche {
    phase: String,
    k: usize,
    alpha: usize,
    beta: usize,
    pref: String,
    finalized: bool,
    cnt: i64,
    rounds: i64,
    d_blue: i64,
    d_red: i64,
}

impl Avalanche {
    pub fn new(phase: &str) -> Result<Self, String> {
        Self::with_params(phase, DEFAULT_K, DEFAULT_ALPHA, DEFAULT_BETA)
    }

    pub fn with_params(phase: &str, k: usize, alpha: usize, beta: usize) -> Result<Self, String> {
        if !PHASES.contains(&phase) {
            return Err("phase must be slush, snowflake, or snowball".into());
        }
        if !(1..=16).contains(&k) {
            return Err("k must be in 1..16".into());
        }
        if !(1..=k).contains(&alpha) || alpha * 2 <= k {
            return Err("alpha must be in 1..k and greater than k/2".into());
        }
        if !(1..=16).contains(&beta) {
            return Err("beta must be in 1..16".into());
        }
        Ok(Self {
            phase: phase.to_owned(),
            k,
            alpha,
            beta,
            pref: String::new(),
            finalized: false,
            cnt: 0,
            rounds: 0,
            d_blue: 0,
            d_red: 0,
        })
    }

    pub fn state_value(&self) -> JsonValue {
        JsonValue::object([
            ("cnt".into(), JsonValue::Number(self.cnt)),
            (
                "d".into(),
                JsonValue::object([
                    ("blue".into(), JsonValue::Number(self.d_blue)),
                    ("red".into(), JsonValue::Number(self.d_red)),
                ]),
            ),
            ("final".into(), JsonValue::Bool(self.finalized)),
            ("phase".into(), JsonValue::String(self.phase.clone())),
            ("pref".into(), JsonValue::String(self.pref.clone())),
            ("rounds".into(), JsonValue::Number(self.rounds)),
        ])
    }

    fn confidence(&self, color: &str) -> i64 {
        match color {
            "blue" => self.d_blue,
            "red" => self.d_red,
            _ => 0,
        }
    }

    fn apply_round(&mut self, winner: Option<&str>) {
        self.rounds += 1;
        let Some(color) = winner else {
            if self.phase == "snowflake" {
                self.cnt = 0;
            }
            return;
        };
        if self.phase == "slush" {
            self.pref = color.to_owned();
            return;
        }
        if self.phase == "snowflake" {
            if self.pref.is_empty() || self.pref == color {
                self.pref = color.to_owned();
                self.cnt += 1;
            } else {
                self.pref = color.to_owned();
                self.cnt = 1;
            }
            if self.cnt >= self.beta as i64 {
                self.finalized = true;
            }
            return;
        }
        match color {
            "blue" => self.d_blue += 1,
            "red" => self.d_red += 1,
            _ => {}
        }
        let d_color = self.confidence(color);
        let d_pref = self.confidence(&self.pref);
        if self.pref.is_empty()
            || d_color > d_pref
            || (d_color == d_pref && color < self.pref.as_str())
        {
            self.pref = color.to_owned();
        }
        if self.confidence(&self.pref) >= self.beta as i64 {
            self.finalized = true;
        }
    }

    fn parse<'a>(&self, message: &'a JsonValue) -> Option<Parsed<'a>> {
        let obj = message.as_object()?;
        if obj.get("consensus").and_then(JsonValue::as_str) != Some("avalanche") {
            return None;
        }
        let op = obj.get("op").and_then(JsonValue::as_str)?;
        if op == "init" {
            let color = obj.get("color").and_then(JsonValue::as_str)?;
            if !COLORS.contains(&color) || !self.pref.is_empty() {
                return None;
            }
            return Some(Parsed::Init(color));
        }
        if op != "round" || self.finalized {
            return None;
        }
        let votes = obj.get("votes").and_then(JsonValue::as_array)?;
        if votes.len() != self.k {
            return None;
        }
        let mut blue = 0usize;
        let mut red = 0usize;
        for vote in votes {
            match vote.as_str()? {
                "blue" => blue += 1,
                "red" => red += 1,
                _ => return None,
            }
        }
        let mut winner = None;
        if blue >= self.alpha {
            winner = Some("blue");
        }
        if red >= self.alpha {
            winner = Some("red");
        }
        Some(Parsed::Round(winner))
    }
}

enum Parsed<'a> {
    Init(&'a str),
    Round(Option<&'a str>),
}

impl ApplicationObject for Avalanche {
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
        match self.parse(message) {
            Some(Parsed::Init(color)) => self.pref = color.to_owned(),
            Some(Parsed::Round(winner)) => self.apply_round(winner),
            None => {}
        }
        Some(self.emit_state_memento())
    }

    fn emit_state_memento(&self) -> StateMemento {
        let payload = JsonValue::object([
            ("state".into(), self.state_value()),
            ("v".into(), JsonValue::Number(1)),
        ]);
        let digest = merkle_digest(&payload).expect("canonical");
        StateMemento::normalize(&digest, &[])
    }

    fn get_state_digests(&self) -> Vec<String> {
        let head = self.emit_state_memento().canonical_digest;
        if head.is_empty() {
            Vec::new()
        } else {
            vec![head]
        }
    }

    fn is_merkelized(&self) -> bool {
        true
    }
}
