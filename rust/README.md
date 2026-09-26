# chaincraft

Rust implementation of the Chaincraft wire protocol and object semantics.

## Install

```bash
cargo add chaincraft
```

## Example

Assumes `chaincraft` is a dependency.

```rust
use chaincraft::{encode_frame, Envelope, JsonValue};

let env = Envelope::build(
    "app.counter",
    JsonValue::object([
        ("by".into(), JsonValue::String("alice".into())),
        ("delta".into(), JsonValue::Number(1)),
    ]),
    None,
)?;
let frame = encode_frame(&env.to_bytes()?)?;
```

Specification and the Python and TypeScript implementations live in the
[monorepo](https://github.com/jose-compu/chaincraft-monorepo).
