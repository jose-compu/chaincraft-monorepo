# chaincraft

Reference implementation of the Chaincraft wire protocol and object semantics.

## Install

```bash
pip install chaincraft
```

Ed25519 is optional: `pip install "chaincraft[ed25519]"`.

## Example

Assumes `chaincraft` is installed.

```python
from chaincraft import Envelope, encode_frame

env = Envelope.build("app.counter", {"by": "alice", "delta": 1})
frame = encode_frame(env.to_bytes())
```

Specification and the Rust and TypeScript implementations live in the
[monorepo](https://github.com/jose-compu/chaincraft-monorepo).
