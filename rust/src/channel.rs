//! Address URIs and an in-process loop channel — SPEC/features/wire-channel.md.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use crate::discovery::{self, is_valid_address};

pub const MAX_LOOP_BYTES: usize = 64;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParsedAddress {
    pub ok: bool,
    pub scheme: String,
    pub canonical: String,
    pub cap: String,
}

fn fail() -> ParsedAddress {
    ParsedAddress {
        ok: false,
        scheme: String::new(),
        canonical: String::new(),
        cap: String::new(),
    }
}

fn ok(scheme: &str, canonical: String) -> ParsedAddress {
    ParsedAddress {
        ok: true,
        scheme: scheme.to_owned(),
        canonical,
        cap: scheme.to_owned(),
    }
}

pub fn parse_address(raw: &str) -> ParsedAddress {
    if raw.is_empty() {
        return fail();
    }
    if let Some(idx) = raw.find("://") {
        let scheme = &raw[..idx];
        let rest = &raw[idx + 3..];
        if scheme != "tcp" && scheme != "udp" {
            return fail();
        }
        if rest.bytes().any(|b| matches!(b, b'@' | b'/' | b'?' | b'#')) {
            return fail();
        }
        if !is_valid_address(rest) {
            return fail();
        }
        return ok(scheme, format!("{scheme}://{rest}"));
    }
    for scheme in ["mailto", "webrtc", "forum", "loop", "pipe"] {
        let prefix = format!("{scheme}:");
        if let Some(rest) = raw.strip_prefix(&prefix) {
            return parse_colon(scheme, rest);
        }
    }
    if is_valid_address(raw) {
        return ok("tcp", format!("tcp://{raw}"));
    }
    fail()
}

pub fn is_connect_allowed(raw: &str) -> bool {
    let parsed = parse_address(raw);
    if !parsed.ok {
        return false;
    }
    if parsed.scheme == "tcp" || parsed.scheme == "udp" {
        let rest = parsed
            .canonical
            .split_once("://")
            .map(|(_, rest)| rest)
            .unwrap_or("");
        return discovery::is_connect_allowed(rest);
    }
    true
}

fn parse_colon(scheme: &str, rest: &str) -> ParsedAddress {
    match scheme {
        "mailto" => {
            let Some((local, domain)) = rest.split_once('@') else {
                return fail();
            };
            if rest.bytes().filter(|b| *b == b'@').count() != 1 {
                return fail();
            }
            if !valid_local(local) || !is_valid_address(&format!("{domain}:1")) {
                return fail();
            }
            ok(scheme, format!("mailto:{rest}"))
        }
        "webrtc" => {
            if rest.len() != 64 || !rest.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')) {
                return fail();
            }
            ok(scheme, format!("webrtc:{rest}"))
        }
        "forum" => {
            let Some((profile, thread)) = rest.split_once(':') else {
                return fail();
            };
            if rest.bytes().filter(|b| *b == b':').count() != 1 {
                return fail();
            }
            if !valid_label(profile) || !valid_thread(thread) {
                return fail();
            }
            ok(scheme, format!("forum:{rest}"))
        }
        "loop" | "pipe" => {
            if !valid_label(rest) {
                return fail();
            }
            ok(scheme, format!("{scheme}:{rest}"))
        }
        _ => fail(),
    }
}

fn valid_local(local: &str) -> bool {
    (1..=64).contains(&local.len())
        && local.bytes().all(
            |b| matches!(b, b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'.' | b'_' | b'+' | b'-'),
        )
}

fn valid_label(name: &str) -> bool {
    let len = name.len();
    if !(1..=32).contains(&len) {
        return false;
    }
    let bytes = name.as_bytes();
    if bytes[0] == b'-' || bytes[len - 1] == b'-' {
        return false;
    }
    bytes
        .iter()
        .all(|b| matches!(b, b'a'..=b'z' | b'0'..=b'9' | b'-'))
}

fn valid_thread(thread: &str) -> bool {
    (1..=64).contains(&thread.len())
        && thread
            .bytes()
            .all(|b| matches!(b, b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'.' | b'_' | b'-'))
}

fn valid_payload(data: &str) -> bool {
    if data.len() < 2 || data.len() % 2 != 0 {
        return false;
    }
    if !data.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')) {
        return false;
    }
    let n = data.len() / 2;
    (1..=MAX_LOOP_BYTES).contains(&n)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InboxItem {
    pub from: String,
    pub data: String,
}

struct BusInner {
    bound: HashMap<String, Rc<RefCell<Vec<InboxItem>>>>,
}

#[derive(Clone)]
pub struct LoopBus {
    inner: Rc<RefCell<BusInner>>,
}

impl LoopBus {
    pub fn new() -> Self {
        Self {
            inner: Rc::new(RefCell::new(BusInner {
                bound: HashMap::new(),
            })),
        }
    }
}

impl Default for LoopBus {
    fn default() -> Self {
        Self::new()
    }
}

pub struct LoopChannel {
    bus: Rc<RefCell<BusInner>>,
    listen: String,
    inbox: Rc<RefCell<Vec<InboxItem>>>,
}

impl LoopChannel {
    pub fn new(bus: &LoopBus) -> Self {
        Self {
            bus: Rc::clone(&bus.inner),
            listen: String::new(),
            inbox: Rc::new(RefCell::new(Vec::new())),
        }
    }

    pub fn listen_addr(&self) -> &str {
        &self.listen
    }

    pub fn inbox(&self) -> Vec<InboxItem> {
        self.inbox.borrow().clone()
    }

    pub fn listen(&mut self, addr: &str) -> bool {
        let parsed = parse_address(addr);
        if !parsed.ok || parsed.scheme != "loop" || !self.listen.is_empty() {
            return false;
        }
        let mut bus = self.bus.borrow_mut();
        if bus.bound.contains_key(&parsed.canonical) {
            return false;
        }
        self.listen = parsed.canonical.clone();
        bus.bound.insert(parsed.canonical, Rc::clone(&self.inbox));
        true
    }

    pub fn dial(&self, addr: &str) -> bool {
        let parsed = parse_address(addr);
        if !parsed.ok || parsed.scheme != "loop" {
            return false;
        }
        self.bus.borrow().bound.contains_key(&parsed.canonical)
    }

    pub fn send(&self, addr: &str, data: &str) -> bool {
        let parsed = parse_address(addr);
        if !parsed.ok || parsed.scheme != "loop" || !valid_payload(data) {
            return false;
        }
        let dest = {
            let bus = self.bus.borrow();
            bus.bound.get(&parsed.canonical).cloned()
        };
        let Some(dest) = dest else {
            return false;
        };
        dest.borrow_mut().push(InboxItem {
            from: self.listen.clone(),
            data: data.to_owned(),
        });
        true
    }

    pub fn recv(&self) -> Vec<InboxItem> {
        std::mem::take(&mut *self.inbox.borrow_mut())
    }

    pub fn close(&mut self) {
        if !self.listen.is_empty() {
            let mut bus = self.bus.borrow_mut();
            if bus
                .bound
                .get(&self.listen)
                .is_some_and(|bound| Rc::ptr_eq(bound, &self.inbox))
            {
                bus.bound.remove(&self.listen);
            }
            self.listen.clear();
        }
        self.inbox.borrow_mut().clear();
    }
}
