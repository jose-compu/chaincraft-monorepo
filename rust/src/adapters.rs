//! Channel adapters — SPEC/features/channel-adapters.md.

use std::cell::RefCell;
use std::collections::HashMap;
use std::net::UdpSocket;
use std::rc::Rc;
use std::time::Duration;

use crate::channel::parse_address;
use crate::framing::MAX_UDP_BYTES;

pub const MAX_UDP_PAYLOAD: usize = MAX_UDP_BYTES;
pub const MAX_MAIL_BYTES: usize = 4096;
pub const MAX_WEBRTC_BYTES: usize = MAX_UDP_PAYLOAD;
pub const MAX_FORUM_BYTES: usize = 4096;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InboxItem {
    pub from: String,
    pub data: String,
}

struct BusInner {
    scheme: String,
    max_bytes: usize,
    bound: HashMap<String, Rc<RefCell<Vec<InboxItem>>>>,
}

#[derive(Clone)]
pub struct AdapterBus {
    inner: Rc<RefCell<BusInner>>,
}

impl AdapterBus {
    pub fn new(scheme: &str, max_bytes: usize) -> Self {
        Self {
            inner: Rc::new(RefCell::new(BusInner {
                scheme: scheme.to_owned(),
                max_bytes,
                bound: HashMap::new(),
            })),
        }
    }

    pub fn udp() -> Self {
        Self::new("udp", MAX_UDP_PAYLOAD)
    }

    pub fn mail() -> Self {
        Self::new("mailto", MAX_MAIL_BYTES)
    }

    pub fn webrtc() -> Self {
        Self::new("webrtc", MAX_WEBRTC_BYTES)
    }

    pub fn forum() -> Self {
        Self::new("forum", MAX_FORUM_BYTES)
    }
}

pub struct AdapterChannel {
    bus: Rc<RefCell<BusInner>>,
    listen: String,
    inbox: Rc<RefCell<Vec<InboxItem>>>,
}

impl AdapterChannel {
    pub fn new(bus: &AdapterBus) -> Self {
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
        let scheme = self.bus.borrow().scheme.clone();
        if !parsed.ok || parsed.scheme != scheme || !self.listen.is_empty() {
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
        let bus = self.bus.borrow();
        parsed.ok && parsed.scheme == bus.scheme && bus.bound.contains_key(&parsed.canonical)
    }

    pub fn send(&self, addr: &str, data: &str) -> bool {
        let parsed = parse_address(addr);
        let (scheme, max_bytes, dest) = {
            let bus = self.bus.borrow();
            (
                bus.scheme.clone(),
                bus.max_bytes,
                bus.bound.get(&parsed.canonical).cloned(),
            )
        };
        if !parsed.ok || parsed.scheme != scheme || !valid_payload(data, max_bytes) {
            return false;
        }
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

fn valid_payload(data: &str, max_bytes: usize) -> bool {
    if data.len() < 2 || data.len() % 2 != 0 {
        return false;
    }
    if !data.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')) {
        return false;
    }
    let n = data.len() / 2;
    (1..=max_bytes).contains(&n)
}

pub struct UdpLink {
    socket: UdpSocket,
}

impl UdpLink {
    pub fn bind() -> std::io::Result<Self> {
        let socket = UdpSocket::bind("127.0.0.1:0")?;
        socket.set_read_timeout(Some(Duration::from_secs(2)))?;
        Ok(Self { socket })
    }

    pub fn host_port(&self) -> std::io::Result<String> {
        Ok(self.socket.local_addr()?.to_string())
    }

    pub fn send(&self, host_port: &str, body: &[u8]) -> std::io::Result<()> {
        if body.is_empty() || body.len() > MAX_UDP_PAYLOAD {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "datagram",
            ));
        }
        self.socket.send_to(body, host_port)?;
        Ok(())
    }

    pub fn recv(&self) -> std::io::Result<(String, Vec<u8>)> {
        let mut buf = vec![0u8; MAX_UDP_PAYLOAD];
        let (n, addr) = self.socket.recv_from(&mut buf)?;
        Ok((addr.to_string(), buf[..n].to_vec()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn localhost_datagram_round_trip() {
        let a = UdpLink::bind().unwrap();
        let b = UdpLink::bind().unwrap();
        let body = b"hello";
        a.send(&b.host_port().unwrap(), body).unwrap();
        let (_from, got) = b.recv().unwrap();
        assert_eq!(got, body);
    }

    #[test]
    fn udp_bus_rejects_oversize() {
        let bus = AdapterBus::udp();
        let mut ch = AdapterChannel::new(&bus);
        assert!(ch.listen("udp://127.0.0.1:1"));
        let ok = "00".repeat(MAX_UDP_PAYLOAD);
        let over = "00".repeat(MAX_UDP_PAYLOAD + 1);
        assert!(ch.send("udp://127.0.0.1:1", &ok));
        assert!(!ch.send("udp://127.0.0.1:1", &over));
    }
}
