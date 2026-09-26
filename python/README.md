# chaincraft

Reference implementation of the Chaincraft wire protocol and object semantics.

```bash
pip install chaincraft
```

```python
from chaincraft import Envelope, encode_frame

env = Envelope.build("app.counter", {"by": "alice", "delta": 1})
frame = encode_frame(env.to_bytes())
```

Ed25519 is optional:

```bash
pip install "chaincraft[ed25519]"
```

Specification and the Rust and TypeScript implementations live in the
[monorepo](https://github.com/jose-compu/chaincraft-monorepo).
