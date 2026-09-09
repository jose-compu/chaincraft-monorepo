//! Canonical JSON — SPEC/wire-v1.md §1 and §2.
//!
//! Encoding follows §1.1–§1.4. Parsing uses its own recursive-descent scanner
//! so duplicate keys (§1.1 rule 2) and float *tokens* (§1.3.1) are rejected
//! before they can be normalized away.

use std::collections::{BTreeMap, HashSet};

use sha2::{Digest, Sha256};

use crate::error::{Error, Result};

pub const MAX_SAFE_INT: i64 = 9_007_199_254_740_991; // 2^53 - 1
pub const MIN_SAFE_INT: i64 = -9_007_199_254_740_991;
pub const MAX_DEPTH: usize = 100;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum JsonValue {
    Null,
    Bool(bool),
    Number(i64),
    String(String),
    Array(Vec<JsonValue>),
    Object(BTreeMap<String, JsonValue>),
}

impl JsonValue {
    pub fn object(pairs: impl IntoIterator<Item = (String, JsonValue)>) -> Self {
        Self::Object(pairs.into_iter().collect())
    }

    pub fn as_object(&self) -> Option<&BTreeMap<String, JsonValue>> {
        match self {
            Self::Object(map) => Some(map),
            _ => None,
        }
    }

    pub fn as_array(&self) -> Option<&[JsonValue]> {
        match self {
            Self::Array(items) => Some(items),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Self::String(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self {
            Self::Number(n) => Some(*n),
            _ => None,
        }
    }
}

fn encode_string(value: &str, out: &mut String) {
    out.push('"');
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{0008}' => out.push_str("\\b"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\u{000c}' => out.push_str("\\f"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn encode(value: &JsonValue, out: &mut String, depth: usize) -> Result<()> {
    if depth > MAX_DEPTH {
        return Err(Error::canonical("value nested too deeply"));
    }
    match value {
        JsonValue::Null => out.push_str("null"),
        JsonValue::Bool(true) => out.push_str("true"),
        JsonValue::Bool(false) => out.push_str("false"),
        JsonValue::Number(n) => {
            if !(MIN_SAFE_INT..=MAX_SAFE_INT).contains(n) {
                return Err(Error::canonical(format!(
                    "integer {n} outside the safe range"
                )));
            }
            // i64 has no -0; zero is already normalized.
            out.push_str(&n.to_string());
        }
        JsonValue::String(s) => encode_string(s, out),
        JsonValue::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                encode(item, out, depth + 1)?;
            }
            out.push(']');
        }
        JsonValue::Object(map) => {
            out.push('{');
            for (i, (key, val)) in map.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                encode_string(key, out);
                out.push(':');
                encode(val, out, depth + 1)?;
            }
            out.push('}');
        }
    }
    Ok(())
}

/// Serialize to canonical JSON text — wire-v1 §1.
pub fn canonical_json(value: &JsonValue) -> Result<String> {
    let mut out = String::new();
    encode(value, &mut out, 0)?;
    Ok(out)
}

pub fn canonical_bytes(value: &JsonValue) -> Result<Vec<u8>> {
    Ok(canonical_json(value)?.into_bytes())
}

/// Payload digest — wire-v1 §2. Lowercase hex SHA-256 over canonical bytes.
pub fn payload_digest(data: &JsonValue) -> Result<String> {
    let bytes = canonical_bytes(data)?;
    Ok(hex::encode(Sha256::digest(&bytes)))
}

// -------------------------------------------------------------------------
// Parser
// -------------------------------------------------------------------------

struct Parser<'a> {
    text: &'a str,
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn new(text: &'a str) -> Self {
        Self {
            text,
            bytes: text.as_bytes(),
            pos: 0,
        }
    }

    fn fail<T>(&self, message: &str) -> Result<T> {
        Err(Error::canonical(format!(
            "{message} at position {}",
            self.pos
        )))
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn skip_ws(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.pos += 1;
        }
    }

    fn expect(&mut self, expected: u8) -> Result<()> {
        match self.peek() {
            Some(ch) if ch == expected => {
                self.pos += 1;
                Ok(())
            }
            _ => self.fail(&format!("expected {}", expected as char)),
        }
    }

    fn parse(&mut self) -> Result<JsonValue> {
        self.skip_ws();
        let value = self.value(0)?;
        self.skip_ws();
        if self.pos < self.bytes.len() {
            return self.fail("unexpected trailing content");
        }
        Ok(value)
    }

    fn value(&mut self, depth: usize) -> Result<JsonValue> {
        if depth > MAX_DEPTH {
            return self.fail("value nested too deeply");
        }
        match self.peek() {
            Some(b'{') => self.object(depth),
            Some(b'[') => self.array(depth),
            Some(b'"') => Ok(JsonValue::String(self.string()?)),
            Some(b't') => self.literal(b"true", JsonValue::Bool(true)),
            Some(b'f') => self.literal(b"false", JsonValue::Bool(false)),
            Some(b'n') => self.literal(b"null", JsonValue::Null),
            Some(b'-' | b'0'..=b'9') => Ok(JsonValue::Number(self.number()?)),
            Some(_) => self.fail("unexpected character"),
            None => self.fail("unexpected end of input"),
        }
    }

    fn literal(&mut self, token: &[u8], value: JsonValue) -> Result<JsonValue> {
        if self.bytes[self.pos..].starts_with(token) {
            self.pos += token.len();
            Ok(value)
        } else {
            self.fail("invalid literal")
        }
    }

    fn number(&mut self) -> Result<i64> {
        let start = self.pos;
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        match self.peek() {
            Some(b'0') => {
                self.pos += 1;
                if matches!(self.peek(), Some(b'0'..=b'9')) {
                    return self.fail("leading zeros are not valid JSON");
                }
            }
            Some(b'1'..=b'9') => {
                while matches!(self.peek(), Some(b'0'..=b'9')) {
                    self.pos += 1;
                }
            }
            _ => return self.fail("invalid number"),
        }
        if matches!(self.peek(), Some(b'.' | b'e' | b'E')) {
            return self.fail("floating-point numbers are not permitted in wire v1");
        }
        let token = &self.text[start..self.pos];
        let value: i64 = token
            .parse()
            .map_err(|_| Error::canonical(format!("integer {token} outside the safe range")))?;
        if !(MIN_SAFE_INT..=MAX_SAFE_INT).contains(&value) {
            return Err(Error::canonical(format!(
                "integer {token} outside the safe range"
            )));
        }
        Ok(value)
    }

    fn string(&mut self) -> Result<String> {
        self.expect(b'"')?;
        let mut out = String::new();
        loop {
            match self.peek() {
                None => return self.fail("unterminated string"),
                Some(b'"') => {
                    self.pos += 1;
                    return Ok(out);
                }
                Some(b'\\') => {
                    self.pos += 1;
                    out.push(self.escape()?);
                }
                Some(ch) if ch < 0x20 => return self.fail("unescaped control character in string"),
                Some(_) => {
                    let ch = self.text[self.pos..]
                        .chars()
                        .next()
                        .ok_or_else(|| Error::canonical("unterminated string"))?;
                    out.push(ch);
                    self.pos += ch.len_utf8();
                }
            }
        }
    }

    fn escape(&mut self) -> Result<char> {
        match self.peek() {
            Some(b'"') => {
                self.pos += 1;
                Ok('"')
            }
            Some(b'\\') => {
                self.pos += 1;
                Ok('\\')
            }
            Some(b'/') => {
                self.pos += 1;
                Ok('/')
            }
            Some(b'b') => {
                self.pos += 1;
                Ok('\u{0008}')
            }
            Some(b'f') => {
                self.pos += 1;
                Ok('\u{000c}')
            }
            Some(b'n') => {
                self.pos += 1;
                Ok('\n')
            }
            Some(b'r') => {
                self.pos += 1;
                Ok('\r')
            }
            Some(b't') => {
                self.pos += 1;
                Ok('\t')
            }
            Some(b'u') => {
                self.pos += 1;
                self.unicode_escape()
            }
            _ => self.fail("invalid escape"),
        }
    }

    fn hex4(&mut self) -> Result<u32> {
        if self.pos + 4 > self.bytes.len() {
            return self.fail("invalid \\u escape");
        }
        let digits = &self.text[self.pos..self.pos + 4];
        if !digits.bytes().all(|b| b.is_ascii_hexdigit()) {
            return self.fail("invalid \\u escape");
        }
        self.pos += 4;
        u32::from_str_radix(digits, 16).map_err(|_| Error::canonical("invalid \\u escape"))
    }

    fn unicode_escape(&mut self) -> Result<char> {
        let first = self.hex4()?;
        if (0xdc00..=0xdfff).contains(&first) {
            return self.fail("lone low surrogate");
        }
        if (0xd800..=0xdbff).contains(&first) {
            if self.peek() != Some(b'\\') || self.bytes.get(self.pos + 1) != Some(&b'u') {
                return self.fail("lone high surrogate");
            }
            self.pos += 2;
            let second = self.hex4()?;
            if !(0xdc00..=0xdfff).contains(&second) {
                return self.fail("high surrogate not followed by a low surrogate");
            }
            let code = 0x10000 + ((first - 0xd800) << 10) + (second - 0xdc00);
            return char::from_u32(code).ok_or_else(|| Error::canonical("invalid code point"));
        }
        char::from_u32(first).ok_or_else(|| Error::canonical("invalid code point"))
    }

    fn array(&mut self, depth: usize) -> Result<JsonValue> {
        self.expect(b'[')?;
        self.skip_ws();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(JsonValue::Array(Vec::new()));
        }
        let mut items = Vec::new();
        loop {
            self.skip_ws();
            items.push(self.value(depth + 1)?);
            self.skip_ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b']') => {
                    self.pos += 1;
                    return Ok(JsonValue::Array(items));
                }
                _ => return self.fail("expected \",\" or \"]\""),
            }
        }
    }

    fn object(&mut self, depth: usize) -> Result<JsonValue> {
        self.expect(b'{')?;
        self.skip_ws();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(JsonValue::Object(BTreeMap::new()));
        }
        let mut map = BTreeMap::new();
        let mut seen = HashSet::new();
        loop {
            self.skip_ws();
            if self.peek() != Some(b'"') {
                return self.fail("expected an object key");
            }
            let key = self.string()?;
            if !seen.insert(key.clone()) {
                return self.fail(&format!("duplicate object key {key:?}"));
            }
            self.skip_ws();
            self.expect(b':')?;
            self.skip_ws();
            let value = self.value(depth + 1)?;
            map.insert(key, value);
            self.skip_ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(JsonValue::Object(map));
                }
                _ => return self.fail("expected \",\" or \"}\""),
            }
        }
    }
}

/// Parse JSON, enforcing the canonical-JSON restrictions on the way in.
pub fn parse_json(text: &str) -> Result<JsonValue> {
    Parser::new(text).parse()
}

pub fn bytes_to_hex(bytes: &[u8]) -> String {
    hex::encode(bytes)
}

pub fn hex_to_bytes(text: &str) -> Result<Vec<u8>> {
    hex::decode(text).map_err(|_| Error::canonical("invalid hex string"))
}
