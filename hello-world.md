# Hello World

Interactive version: open [`index.html`](index.html) in this folder, or the published site.

This walks through a gossiped message on Chaincraft 1.0.0. The control channel is JSON lines. Python, Rust, and TypeScript speak the same commands and produce the same payload id.

## Install

Python 3.9+, a Rust toolchain, and Node 22.6+. From the clone root:

```bash
git clone https://github.com/jose-compu/chaincraft-monorepo.git
cd chaincraft-monorepo
python3 -m pip install -e "./python[dev]"
cargo build --bin node --manifest-path rust/Cargo.toml
npm install --prefix typescript
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

## Run three nodes

Stay at the clone root.

```bash
# Terminal 1
python3 -m chaincraft_core.node

# Terminal 2
cargo run --bin node --manifest-path rust/Cargo.toml

# Terminal 3
npm run node --prefix typescript
```

Read `addr` from the first `ready` event. On terminal 2 and terminal 3:

```json
{"cmd":"connect","addr":"127.0.0.1:PORT"}
```

On terminal 1:

```json
{"cmd":"send","type":"app.hello","data":{"message":"Hello, Chaincraft!"}}
```

`sent.id` is SHA-256 of the canonical payload. After `ctl.hello`, the other two nodes print `received` with that same id. `{"cmd":"ids"}` lists it on every node. `{"cmd":"quit"}` stops a node.

## The same program in each language

These do not open a socket. Each one implements `receive`, prints the message, frames the envelope, and prints the same id. A memento is not involved.

### Python

Save as `hello.py` and run `python3 hello.py`.

```python
from chaincraft_core import Envelope, encode_frame
from chaincraft_core.object import SharedObject


class HelloObject(SharedObject):
    def receive(self, message):
        print("Received:", message["message"])


data = {"message": "Hello, Chaincraft!"}
HelloObject().receive(data)

env = Envelope.build("app.hello", data)
frame = encode_frame(env.to_bytes())
print(env.id)
print("frame_len", len(frame))
```

### Rust

Save the manifest as `hello/Cargo.toml` and the program as `hello/src/main.rs`. Then `cargo run --manifest-path hello/Cargo.toml`.

Implement `Protocol` and `receive`. `Envelope::build` takes the timestamp as a third argument. `None` uses the clock. The digest does not.

```toml
[package]
name = "hello"
version = "0.1.0"
edition = "2021"

[dependencies]
chaincraft-core = { path = "../rust" }
```

```rust
use chaincraft_core::{encode_frame, parse_json, Envelope, JsonValue, Protocol};

struct HelloObject;

impl Protocol for HelloObject {
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
    let data = parse_json(r#"{"message":"Hello, Chaincraft!"}"#).unwrap();
    HelloObject.receive(&data);

    let env = Envelope::build("app.hello", data, None).unwrap();
    let frame = encode_frame(&env.to_bytes().unwrap()).unwrap();
    println!("{}", env.id);
    println!("frame_len {}", frame.len());
}
```

### TypeScript

Save as `typescript/hello.ts` and run `node hello.ts` from `typescript/`. Override `receive`.

```typescript
import {
  BaseSharedObject,
  Envelope,
  encodeFrame,
  type JsonValue,
} from "./src/index.ts";

class HelloObject extends BaseSharedObject {
  receive(message: JsonValue): void {
    console.log("Received:", (message as { message: string }).message);
  }
}

const data = { message: "Hello, Chaincraft!" };
new HelloObject().receive(data);

const env = Envelope.build("app.hello", data);
const frame = encodeFrame(env.toBytes());
console.log(env.id);
console.log("frame_len", frame.length);
```

The live 3×3 check is `python3 conformance/runner/run_interop.py` from the repository root.
