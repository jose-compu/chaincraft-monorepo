//! BitTorrent mesh client — Swarm on top of the Level 0 mesh.

use std::io::BufRead;
use std::sync::Arc;

use chaincraft_core::bittorrent::{Client, WIRE_TYPE};
use chaincraft_core::features::IMPL;
use chaincraft_core::mesh::{emit, json_to_serde, to_json_value, Mesh};
use serde_json::{json, Value};

const MAX_STDIN_LINE: usize = 1_048_576;

fn main() {
    let mesh = Mesh::start().expect("bind");
    let client = Arc::new(Client::new());
    {
        let mesh_for_app = Arc::clone(&mesh);
        let client_for_app = Arc::clone(&client);
        mesh.lock()
            .unwrap()
            .set_on_app(Arc::new(move |type_name, data| {
                if let Some(reply) = client_for_app.on_app(type_name, data) {
                    let _ = Mesh::broadcast(&mesh_for_app, WIRE_TYPE, reply);
                }
            }));
    }
    let listen_addr = mesh.lock().unwrap().listen_addr().to_string();
    emit(json!({"event":"ready","addr":listen_addr,"impl":IMPL}));

    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.len() > MAX_STDIN_LINE {
            emit(json!({"event":"error","message":"line too long"}));
            continue;
        }
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
                match Mesh::connect(&mesh, addr) {
                    Ok(()) => emit(json!({"event":"connected","addr":addr})),
                    Err(err) => emit(json!({"event":"error","message":err})),
                }
            }
            Some("send") => {
                let type_name = cmd["type"].as_str().unwrap_or("app.interop");
                match to_json_value(&cmd["data"]) {
                    Ok(data) => match Mesh::broadcast(&mesh, type_name, data) {
                        Ok(id) => emit(json!({"event":"sent","id":id})),
                        Err(err) => emit(json!({"event":"error","message":err})),
                    },
                    Err(err) => emit(json!({"event":"error","message":err})),
                }
            }
            Some("ids") => {
                let ids = mesh.lock().unwrap().ids();
                emit(json!({"event":"ids","ids":ids}));
            }
            Some("bt.seed") => {
                let peer = cmd["peer"].as_str().unwrap_or("");
                let name = cmd["name"].as_str().unwrap_or("");
                let payload = cmd["data"].as_str().unwrap_or("");
                let piece_size = cmd["piece_size"].as_u64().unwrap_or(0) as usize;
                match client.seed(peer, name, payload, piece_size) {
                    Ok((messages, info_hash, length, pieces)) => {
                        let mut failed = false;
                        for message in messages {
                            if let Err(err) = Mesh::broadcast(&mesh, WIRE_TYPE, message) {
                                emit(json!({"event":"error","message":err}));
                                failed = true;
                                break;
                            }
                        }
                        if !failed {
                            emit(json!({
                                "event":"bt.seeded",
                                "info_hash":info_hash,
                                "length":length,
                                "pieces":pieces
                            }));
                        }
                    }
                    Err(err) => emit(json!({"event":"error","message":err})),
                }
            }
            Some("bt.leech") => {
                let peer = cmd["peer"].as_str().unwrap_or("");
                let digest = cmd.get("info_hash").and_then(Value::as_str);
                match client.leech(peer, digest) {
                    Ok((messages, info_hash, requested)) => {
                        let mut failed = false;
                        for message in messages {
                            if let Err(err) = Mesh::broadcast(&mesh, WIRE_TYPE, message) {
                                emit(json!({"event":"error","message":err}));
                                failed = true;
                                break;
                            }
                        }
                        if !failed {
                            emit(
                                json!({"event":"bt.leech","info_hash":info_hash,"requested":requested}),
                            );
                        }
                    }
                    Err(err) => emit(json!({"event":"error","message":err})),
                }
            }
            Some("bt.status") => match client.status() {
                Ok(value) => emit(json_to_serde(&value)),
                Err(err) => emit(json!({"event":"error","message":err})),
            },
            Some("quit") => break,
            other => emit(json!({"event":"error","message":format!("unknown cmd {other:?}")})),
        }
    }
}
