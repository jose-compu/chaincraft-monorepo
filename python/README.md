# chaincraft

Reference implementation of the Chaincraft wire protocol and object semantics.
Release **1.0.0**.

Open-source toolkit for peer-to-peer protocols like blockchains, chat rooms,
BitTorrent swarms, and content-addressed stores.

## Install

```bash
pip install chaincraft
```

PyPI still indexes 0.8.0 as latest. Until `chaincraft==1.0.0` is there:

```bash
pip install "git+https://github.com/jose-compu/chaincraft-monorepo.git@v1.0.0#subdirectory=python"
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
