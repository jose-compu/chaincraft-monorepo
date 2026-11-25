# Hello World

Interactive version: open [`index.html`](index.html) in this folder, or the published site.

Open-source toolkit for peer-to-peer protocols like blockchains. This walks through a gossiped message on Chaincraft 1.10.0 over **TCP sockets**: default bind `0.0.0.0:9735`, local dial `127.0.0.1:9735`, two nodes in one program, then a three-language mesh on loopback or across hosts. The control channel is JSON lines. Python, Rust, and TypeScript speak the same commands and produce the same payload id.

Published: [`chaincraft` 1.10.0 on PyPI](https://pypi.org/project/chaincraft/1.10.0/), [`chaincraft` 1.10.0 on crates.io](https://crates.io/crates/chaincraft/1.10.0), [`@chaincraft/core` 1.10.0 on npm](https://www.npmjs.com/package/@chaincraft/core/v/1.10.0).

## Install

```bash
pip install chaincraft
cargo install chaincraft
npm install --global @chaincraft/core
```

Libraries (for the programs later): `cargo add chaincraft`, `npm install @chaincraft/core`.

A browser page imports `@chaincraft/core/browser`. That entry does not import the TCP mesh. `fetchPeerId()` reads `GET /peerjs/id` from `https://dechess-org-peerjs.vercel.app`, and `peerOptions()` is what you pass to `Peer`. The data channel is yours.

Clone only as a fallback if you want the source tree:

```bash
git clone https://github.com/jose-compu/chaincraft-monorepo.git
```

## Commands

Each stdin line is one JSON object.

| `cmd` | Fields | Effect |
|---|---|---|
| `connect` | `addr` | Dial `host:port` and complete `ctl.hello` |
| `send` | `type`, `data` | Broadcast an application envelope |
| `ids` | — | List payload ids this process has recorded |
| `quit` | — | Stop the process |

Stdout events:

| event | Fields |
|---|---|
| `ready` | `addr`, `impl` |
| `hello` | `peer`, `addr` |
| `connected` | `addr` |
| `sent` | `id` |
| `received` | `id`, `type` |
| `ids` | `ids` |
| `error` | `message` |

`received` may also include `data`. Rust's node prints `id` and `type`.

The core node is connect / send / ids / quit. BitTorrent is a Mesh client (`python3 -m chaincraft.bt_node`, `chaincraft-bt-node`, `chaincraft-ts-bt-node`).

## One node on the default port

With no argument the node binds `0.0.0.0:9735`. Local Hello World still dials `127.0.0.1:9735`.

```bash
python3 -m chaincraft.node
```

```json
{"event":"ready","addr":"0.0.0.0:9735","impl":"py-chaincraft/1.10.0"}
```

Same default in Rust (`chaincraft-node`) and TypeScript (`chaincraft-ts-node`). Pass `host:port` to override. `127.0.0.1:0` is ephemeral.

## Two TCP nodes in one program

These open real sockets. Node A listens on `9735`, node B on `9736`, B dials A, then B gossips `app.hello`. Both record the same payload id.

### Python

Save as `hello.py` and run `python3 hello.py`.

```python
import time
from chaincraft.mesh import Mesh
from chaincraft.object import SharedObject


class Hello(SharedObject):
    def receive(self, message):
        print("Received:", message["message"])


hello = Hello()
a = Mesh(on_app=lambda t, d: hello.receive(d) if t == "app.hello" else None)
b = Mesh()
print("listening", a.start("127.0.0.1", 9735))
print("listening", b.start("127.0.0.1", 9736))
b.connect(a.listen_addr)
digest = b.broadcast("app.hello", {"message": "Hello, Chaincraft!"})
time.sleep(0.4)
print(digest)
print(a.ids())
a.close()
b.close()
```

### Rust

After `cargo add chaincraft`, save as `src/main.rs` and run `cargo run`.

```toml
[package]
name = "hello"
version = "0.1.0"
edition = "2021"

[dependencies]
chaincraft = "1.10.0"
```

```rust
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use chaincraft::mesh::Mesh;
use chaincraft::{parse_json, JsonValue, Protocol};

struct Hello;

impl Protocol for Hello {
    fn receive(&mut self, message: &JsonValue) {
        let text = message
            .as_object()
            .and_then(|obj| obj.get("message"))
            .and_then(|value| value.as_str())
            .unwrap_or("");
        println!("Received: {text}");
    }
}

fn main() {
    let a = Mesh::bind("127.0.0.1:9735").unwrap();
    let b = Mesh::bind("127.0.0.1:9736").unwrap();
    a.lock().unwrap().set_on_app(Arc::new(|_t, data| {
        Hello.receive(data);
    }));
    Mesh::connect(&b, "127.0.0.1:9735").unwrap();
    let data = parse_json(r#"{"message":"Hello, Chaincraft!"}"#).unwrap();
    let id = Mesh::broadcast(&b, "app.hello", data).unwrap();
    thread::sleep(Duration::from_millis(400));
    println!("{id}");
}
```

### TypeScript

After `npm install @chaincraft/core`, save as `hello.mjs` and run `node hello.mjs`.

```js
import { Mesh } from "@chaincraft/core";

const a = new Mesh();
const b = new Mesh();
a.onApp = (_t, data) => {
  console.log("Received:", data.message);
};

console.log("listening", await a.start("127.0.0.1", 9735));
console.log("listening", await b.start("127.0.0.1", 9736));
await b.connect(a.listenAddr);
const id = b.broadcast("app.hello", { message: "Hello, Chaincraft!" });
await new Promise((r) => setTimeout(r, 400));
console.log(id);
a.close();
b.close();
```

## Three nodes, one language each

Python holds `9735`. Rust binds `9736`. TypeScript binds `9737`. Both dial Python.

```bash
# Terminal 1 — Python
python3 -m chaincraft.node

# Terminal 2 — Rust
chaincraft-node 127.0.0.1:9736

# Terminal 3 — TypeScript
chaincraft-ts-node 127.0.0.1:9737
# fallback: node node_modules/@chaincraft/core/dist/node.js 127.0.0.1:9737
```

If a node prints a different `ready.addr`, connect to that address.

On terminal 2 and terminal 3:

```json
{"cmd":"connect","addr":"127.0.0.1:9735"}
```

On terminal 1:

```json
{"cmd":"send","type":"app.hello","data":{"message":"Hello, Chaincraft!"}}
```

`sent.id` is SHA-256 of the canonical payload. After `ctl.hello`, Rust and TypeScript print `received` with that same id. `{"cmd":"ids"}` lists it on every node. Send from any language; the other two receive it. `{"cmd":"quit"}` stops a node.

## More nodes, local or LAN

Start further processes on unused ports and `connect` them to a node that is already listening. Each mesh keeps at most 256 peers.

`connect` allows loopback, RFC1918, public unicast IPv4, `localhost`, `.local`, and ordinary DNS names. Unspecified, link-local, multicast, and reserved addresses are refused. Default bind is `0.0.0.0:9735`.

```bash
python3 -m chaincraft.node
# other host
python3 -m chaincraft.node 0.0.0.0:9736
# then: {"cmd":"connect","addr":"203.0.113.10:9735"}
```

The live 3×3 check is `python3 conformance/runner/run_interop.py` from the repository root.

Release: https://github.com/jose-compu/chaincraft-monorepo/releases/tag/v1.10.0
