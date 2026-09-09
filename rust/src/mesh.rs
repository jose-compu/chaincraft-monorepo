//! TCP mesh — SPEC/wire-v1.md §4, §5, §7, §8.
//!
//! Application protocols attach via `on_app`, not by editing this module.

use std::io::{Read, Write};
use std::net::{IpAddr, TcpListener, TcpStream, ToSocketAddrs};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde_json::{json, Map, Value};

use crate::canonical::JsonValue;
use crate::control::{self, parse_hello};
use crate::dedup::Deduplicator;
use crate::discovery::{is_connect_allowed, is_resolved_ip_allowed};
use crate::envelope::Envelope;
use crate::features::IMPL;
use crate::framing::{encode_frame, FrameReader};

pub const MAX_PEERS: usize = 16;
pub const MAX_RECEIVED: usize = 4096;
pub const NODE_MAX_FRAME: u32 = 262_144;

pub type AppHandler = Arc<dyn Fn(&str, &JsonValue) + Send + Sync>;

struct Peer {
    stream: TcpStream,
    addr: String,
}

pub struct Mesh {
    impl_name: String,
    listen_addr: String,
    dedup: Deduplicator,
    peers: Vec<Arc<Mutex<Peer>>>,
    received: Vec<String>,
    on_app: Option<AppHandler>,
}

impl Mesh {
    pub fn start() -> Result<Arc<Mutex<Self>>, String> {
        let listener = TcpListener::bind("127.0.0.1:0").map_err(|err| err.to_string())?;
        let listen_addr = listener
            .local_addr()
            .map_err(|err| err.to_string())?
            .to_string();
        let mesh = Arc::new(Mutex::new(Self {
            impl_name: IMPL.to_string(),
            listen_addr: listen_addr.clone(),
            dedup: Deduplicator::default(),
            peers: Vec::new(),
            received: Vec::new(),
            on_app: None,
        }));
        let accept_mesh = Arc::clone(&mesh);
        thread::spawn(move || {
            for incoming in listener.incoming() {
                match incoming {
                    Ok(stream) => {
                        let addr = stream
                            .peer_addr()
                            .map(|a| a.to_string())
                            .unwrap_or_else(|_| "unknown".into());
                        add_peer(&accept_mesh, stream, addr);
                    }
                    Err(err) => emit(json!({"event":"error","message":err.to_string()})),
                }
            }
        });
        Ok(mesh)
    }

    pub fn listen_addr(&self) -> &str {
        &self.listen_addr
    }

    pub fn set_on_app(&mut self, handler: AppHandler) {
        self.on_app = Some(handler);
    }

    pub fn ids(&self) -> Vec<String> {
        self.received.clone()
    }

    pub fn connect(mesh: &Arc<Mutex<Self>>, addr: &str) -> Result<(), String> {
        let stream = dial(addr)?;
        add_peer(mesh, stream, addr.to_string());
        Ok(())
    }

    pub fn broadcast(
        mesh: &Arc<Mutex<Self>>,
        type_name: &str,
        data: JsonValue,
    ) -> Result<String, String> {
        let env = Envelope::build(type_name, data, None).map_err(|e| e.to_string())?;
        let (peers, handler) = {
            let mut guard = mesh.lock().map_err(|e| e.to_string())?;
            let fresh = guard.dedup.should_process(&env);
            if fresh {
                record(&mut guard, env.id.clone());
            }
            let peers = if fresh {
                Some(guard.peers.clone())
            } else {
                None
            };
            (peers, if fresh { guard.on_app.clone() } else { None })
        };
        if let Some(peers) = peers {
            for peer in peers {
                write_env(&peer, &env)?;
            }
        }
        if let Some(handler) = handler {
            handler(type_name, &env.data);
        }
        Ok(env.id)
    }
}

pub fn json_to_serde(value: &JsonValue) -> Value {
    match value {
        JsonValue::Null => Value::Null,
        JsonValue::Bool(flag) => json!(flag),
        JsonValue::Number(number) => json!(number),
        JsonValue::String(text) => json!(text),
        JsonValue::Array(items) => Value::Array(items.iter().map(json_to_serde).collect()),
        JsonValue::Object(map) => {
            let mut object = Map::new();
            for (key, item) in map {
                object.insert(key.clone(), json_to_serde(item));
            }
            Value::Object(object)
        }
    }
}

pub fn emit(event: Value) {
    static OUT: Mutex<()> = Mutex::new(());
    let _guard = OUT.lock();
    let mut out = std::io::stdout();
    writeln!(out, "{event}").ok();
    out.flush().ok();
}

pub fn to_json_value(value: &Value) -> Result<JsonValue, String> {
    match value {
        Value::Null => Ok(JsonValue::Null),
        Value::Bool(b) => Ok(JsonValue::Bool(*b)),
        Value::Number(n) => n
            .as_i64()
            .map(JsonValue::Number)
            .ok_or_else(|| format!("unsupported number {n}")),
        Value::String(s) => Ok(JsonValue::String(s.clone())),
        Value::Array(items) => {
            let converted = items
                .iter()
                .map(to_json_value)
                .collect::<Result<Vec<_>, _>>()?;
            Ok(JsonValue::Array(converted))
        }
        Value::Object(map) => {
            let mut obj = Vec::new();
            for (k, v) in map {
                obj.push((k.clone(), to_json_value(v)?));
            }
            Ok(JsonValue::object(obj))
        }
    }
}

fn record(mesh: &mut Mesh, id: String) {
    if mesh.received.len() >= MAX_RECEIVED {
        mesh.received.remove(0);
    }
    mesh.received.push(id);
}

fn dial(addr: &str) -> Result<TcpStream, String> {
    if !is_connect_allowed(addr) {
        return Err("address not allowed".into());
    }
    let resolved = addr
        .to_socket_addrs()
        .map_err(|err| err.to_string())?
        .find(|item| matches!(item.ip(), IpAddr::V4(_)))
        .ok_or_else(|| "unresolvable".to_string())?;
    let ip = match resolved.ip() {
        IpAddr::V4(v4) => v4.to_string(),
        IpAddr::V6(_) => return Err("address not allowed".into()),
    };
    if !is_resolved_ip_allowed(&ip) {
        return Err("address not allowed".into());
    }
    let stream = TcpStream::connect_timeout(&resolved, Duration::from_secs(5))
        .map_err(|err| err.to_string())?;
    stream.set_nodelay(true).ok();
    stream.set_write_timeout(Some(Duration::from_secs(5))).ok();
    Ok(stream)
}

fn write_env(peer: &Arc<Mutex<Peer>>, env: &Envelope) -> Result<(), String> {
    let bytes = env.to_bytes().map_err(|e| e.to_string())?;
    let frame = encode_frame(&bytes).map_err(|e| e.to_string())?;
    let mut guard = peer.lock().map_err(|e| e.to_string())?;
    guard.stream.write_all(&frame).map_err(|e| e.to_string())?;
    Ok(())
}

fn add_peer(mesh: &Arc<Mutex<Mesh>>, stream: TcpStream, addr: String) {
    stream.set_nodelay(true).ok();
    stream.set_write_timeout(Some(Duration::from_secs(5))).ok();
    let stream_for_read = match stream.try_clone() {
        Ok(clone) => clone,
        Err(err) => {
            emit(json!({"event":"error","message":err.to_string()}));
            return;
        }
    };
    let peer = Arc::new(Mutex::new(Peer {
        stream,
        addr: addr.clone(),
    }));
    let hello = {
        let guard = mesh.lock().unwrap();
        control::hello(&guard.impl_name, None, Some(&guard.listen_addr), None)
    };
    match hello {
        Ok(env) => {
            if let Err(err) = write_env(&peer, &env) {
                emit(json!({"event":"error","message":err}));
                return;
            }
        }
        Err(err) => {
            emit(json!({"event":"error","message":err.to_string()}));
            return;
        }
    }
    {
        let mut guard = mesh.lock().unwrap();
        if guard.peers.len() >= MAX_PEERS {
            return;
        }
        guard.peers.push(Arc::clone(&peer));
    }
    let mesh_for_read = Arc::clone(mesh);
    thread::spawn(move || read_loop(mesh_for_read, peer, stream_for_read));
}

fn read_loop(mesh: Arc<Mutex<Mesh>>, peer: Arc<Mutex<Peer>>, stream: TcpStream) {
    let mut reader = FrameReader::with_max(NODE_MAX_FRAME);
    let mut incoming = stream;
    let mut buf = [0u8; 8192];
    loop {
        match incoming.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => match reader.feed(&buf[..n]) {
                Ok(frames) => {
                    for body in frames {
                        if let Err(err) = handle(&mesh, &peer, &body) {
                            emit(json!({"event":"error","message":err}));
                            break;
                        }
                    }
                }
                Err(err) => {
                    emit(json!({"event":"error","message":err.to_string()}));
                    break;
                }
            },
            Err(err) => {
                emit(json!({"event":"error","message":err.to_string()}));
                break;
            }
        }
    }
    if let Ok(mut guard) = mesh.lock() {
        guard.peers.retain(|p| !Arc::ptr_eq(p, &peer));
    }
}

fn handle(mesh: &Arc<Mutex<Mesh>>, peer: &Arc<Mutex<Peer>>, body: &[u8]) -> Result<(), String> {
    let env = Envelope::parse_bytes(body, None).map_err(|e| e.to_string())?;
    if env.is_control() {
        if env.type_name == control::HELLO {
            let hello = parse_hello(&env).map_err(|e| e.to_string())?;
            let addr = peer.lock().map_err(|e| e.to_string())?.addr.clone();
            emit(json!({"event":"hello","peer":hello.impl_name,"addr":addr}));
        }
        return Ok(());
    }
    let (should_relay, others, handler) = {
        let mut guard = mesh.lock().map_err(|e| e.to_string())?;
        if !guard.dedup.should_process(&env) {
            return Ok(());
        }
        record(&mut guard, env.id.clone());
        let should_relay = guard.dedup.should_relay(&env);
        let others = guard.peers.clone();
        (should_relay, others, guard.on_app.clone())
    };
    emit(json!({"event":"received","id":env.id,"type":env.type_name}));
    if should_relay {
        for other in others {
            if Arc::ptr_eq(&other, peer) {
                continue;
            }
            let _ = write_env(&other, &env);
        }
    }
    if let Some(handler) = handler {
        handler(&env.type_name, &env.data);
    }
    Ok(())
}
