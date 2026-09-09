//! Minimal TCP mesh node — SPEC/wire-v1.md §4, §5, §7, §8.

use std::io::{BufRead, Read, Write}; // BufRead for stdin lines; Read for TCP
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::thread;

use chaincraft_core::canonical::JsonValue;
use chaincraft_core::control::{self, parse_hello};
use chaincraft_core::dedup::Deduplicator;
use chaincraft_core::envelope::Envelope;
use chaincraft_core::features::IMPL;
use chaincraft_core::framing::{encode_frame, FrameReader};
use serde_json::{json, Value};

struct Peer {
    stream: TcpStream,
    addr: String,
}

struct Mesh {
    impl_name: String,
    listen_addr: String,
    dedup: Deduplicator,
    peers: Vec<Arc<Mutex<Peer>>>,
    received: Vec<String>,
}

fn emit(event: Value) {
    let mut out = std::io::stdout();
    writeln!(out, "{event}").ok();
    out.flush().ok();
}

fn to_json_value(value: &Value) -> Result<JsonValue, String> {
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

fn write_env(peer: &Arc<Mutex<Peer>>, env: &Envelope) -> Result<(), String> {
    let bytes = env.to_bytes().map_err(|e| e.to_string())?;
    let frame = encode_frame(&bytes).map_err(|e| e.to_string())?;
    let mut guard = peer.lock().map_err(|e| e.to_string())?;
    guard.stream.write_all(&frame).map_err(|e| e.to_string())?;
    Ok(())
}

fn add_peer(mesh: &Arc<Mutex<Mesh>>, stream: TcpStream, addr: String) {
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
        guard.peers.push(Arc::clone(&peer));
    }
    let mesh_for_read = Arc::clone(mesh);
    thread::spawn(move || read_loop(mesh_for_read, peer, stream_for_read));
}

fn read_loop(mesh: Arc<Mutex<Mesh>>, peer: Arc<Mutex<Peer>>, stream: TcpStream) {
    let mut reader = FrameReader::new();
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
    let (should_relay, others) = {
        let mut guard = mesh.lock().map_err(|e| e.to_string())?;
        if !guard.dedup.should_process(&env) {
            return Ok(());
        }
        guard.received.push(env.id.clone());
        let should_relay = guard.dedup.should_relay(&env);
        let others = guard.peers.clone();
        (should_relay, others)
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
    Ok(())
}

fn broadcast(mesh: &Arc<Mutex<Mesh>>, type_name: &str, data: JsonValue) -> Result<String, String> {
    let env = Envelope::build(type_name, data, None).map_err(|e| e.to_string())?;
    let peers = {
        let mut guard = mesh.lock().map_err(|e| e.to_string())?;
        let fresh = guard.dedup.should_process(&env);
        if fresh {
            guard.received.push(env.id.clone());
        }
        if fresh {
            Some(guard.peers.clone())
        } else {
            None
        }
    };
    if let Some(peers) = peers {
        for peer in peers {
            write_env(&peer, &env)?;
        }
    }
    Ok(env.id)
}

fn main() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
    let listen_addr = listener.local_addr().expect("local addr").to_string();
    let mesh = Arc::new(Mutex::new(Mesh {
        impl_name: IMPL.to_string(),
        listen_addr: listen_addr.clone(),
        dedup: Deduplicator::default(),
        peers: Vec::new(),
        received: Vec::new(),
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

    emit(json!({"event":"ready","addr":listen_addr,"impl":IMPL}));

    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let line = line.trim().to_string();
        if line.is_empty() {
            continue;
        }
        let cmd: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(err) => {
                emit(json!({"event":"error","message":err.to_string()}));
                continue;
            }
        };
        match cmd.get("cmd").and_then(Value::as_str) {
            Some("connect") => {
                let addr = cmd["addr"].as_str().unwrap_or("");
                match TcpStream::connect(addr) {
                    Ok(stream) => {
                        add_peer(&mesh, stream, addr.to_string());
                        emit(json!({"event":"connected","addr":addr}));
                    }
                    Err(err) => emit(json!({"event":"error","message":err.to_string()})),
                }
            }
            Some("send") => {
                let type_name = cmd["type"].as_str().unwrap_or("app.interop");
                match to_json_value(&cmd["data"]) {
                    Ok(data) => match broadcast(&mesh, type_name, data) {
                        Ok(id) => emit(json!({"event":"sent","id":id})),
                        Err(err) => emit(json!({"event":"error","message":err})),
                    },
                    Err(err) => emit(json!({"event":"error","message":err})),
                }
            }
            Some("ids") => {
                let ids = mesh.lock().unwrap().received.clone();
                emit(json!({"event":"ids","ids":ids}));
            }
            Some("quit") => break,
            other => emit(json!({"event":"error","message":format!("unknown cmd {other:?}")})),
        }
    }
}
