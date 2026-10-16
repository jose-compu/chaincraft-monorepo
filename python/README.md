# chaincraft

Reference implementation of the Chaincraft wire protocol and object semantics.
Release **1.0.0**.

Open-source toolkit for peer-to-peer protocols like blockchains, chat rooms,
BitTorrent swarms, and content-addressed stores.

## Install

PyPI still serves the pre-rewrite 0.8.0 line. Until
[chaincraft 1.0.0](https://pypi.org/project/chaincraft/) is published there:

```bash
git clone --branch v1.0.0 https://github.com/jose-compu/chaincraft-monorepo.git
cd chaincraft-monorepo
python3 -m pip install -e "./python[ed25519]"
```

After 1.0.0 is on PyPI: `pip install chaincraft`. Ed25519 is optional:
`pip install "chaincraft[ed25519]"`.

## Example

Assumes `chaincraft` is installed.

```python
from chaincraft import Envelope, encode_frame

env = Envelope.build("app.counter", {"by": "alice", "delta": 1})
frame = encode_frame(env.to_bytes())
```

Specification and the Rust and TypeScript implementations live in the
[monorepo](https://github.com/jose-compu/chaincraft-monorepo).
