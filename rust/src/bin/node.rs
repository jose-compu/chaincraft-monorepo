//! Minimal TCP mesh node — SPEC/wire-v1.md §4, §5, §7, §8.

use std::io::BufRead;

use chaincraft::features::IMPL;
use chaincraft::mesh::{emit, to_json_value, Mesh, DEFAULT_LISTEN};
use serde_json::{json, Value};

const MAX_STDIN_LINE: usize = 1_048_576;

fn main() {
    let listen = std::env::args()
        .nth(1)
        .unwrap_or_else(|| DEFAULT_LISTEN.to_string());
    let mesh = Mesh::bind(&listen).expect("bind");
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
            Some("quit") => break,
            other => emit(json!({"event":"error","message":format!("unknown cmd {other:?}")})),
        }
    }
}
