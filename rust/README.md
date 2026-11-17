# chaincraft

Rust implementation of the Chaincraft wire protocol and object semantics.
Release **[1.7.0](https://crates.io/crates/chaincraft/1.7.0)** on crates.io.
1.7.0 adds `consensus.poet` (Proof of Elapsed Time on a shared Sloth seed).
47 of 47 registry features.

Open-source toolkit for peer-to-peer protocols like blockchains, chat rooms,
BitTorrent swarms, and content-addressed stores.

## Install

```bash
cargo add chaincraft
cargo install chaincraft
```

The node binary is `chaincraft-node`. Default listen is `0.0.0.0:9735`.

## Hello World

Two TCP nodes in one process. A listens on `9735`, B on `9736`, B dials A and
gossips `app.hello`.

```toml
[dependencies]
chaincraft = "1.7.0"
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

CLI, three languages on one loopback mesh:

```bash
python3 -m chaincraft.node
chaincraft-node 127.0.0.1:9736
chaincraft-ts-node 127.0.0.1:9737
```

Then `{"cmd":"connect","addr":"127.0.0.1:9735"}` on the last two, and
`{"cmd":"send","type":"app.hello","data":{"message":"Hello, Chaincraft!"}}` on
Python.

Further local nodes take unused ports and connect. Remote hosts dial this
machine's unicast IPv4 or DNS name on 9735. `connect` allows loopback,
RFC1918, public unicast IPv4, `localhost`, `.local`, and ordinary DNS names.
One mesh process keeps at most 256 live peers.

Specification and the Python and TypeScript implementations live in the
[monorepo](https://github.com/jose-compu/chaincraft-monorepo).
