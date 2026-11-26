# chaincraft

[![CI](https://github.com/jose-compu/chaincraft-monorepo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jose-compu/chaincraft-monorepo/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/chaincraft?style=flat-square)](https://pypi.org/project/chaincraft/)
[![PyPI downloads](https://img.shields.io/pypi/dm/chaincraft?style=flat-square)](https://pypi.org/project/chaincraft/)
[![PyPI total downloads](https://img.shields.io/pepy/dt/chaincraft?style=flat-square)](https://pepy.tech/project/chaincraft)
[![python versions](https://img.shields.io/pypi/pyversions/chaincraft?style=flat-square)](https://pypi.org/project/chaincraft/)
[![License: MIT](https://img.shields.io/github/license/jose-compu/chaincraft-monorepo?style=flat-square)](https://github.com/jose-compu/chaincraft-monorepo/blob/main/LICENSE)

Reference implementation of the Chaincraft wire protocol and object semantics.
Release **[1.12.0](https://pypi.org/project/chaincraft/1.12.0/)** on PyPI.
1.12.0 adds `chain.transfer` and `node.preset`.
53 of 53 registry features are implemented in Python.

Open-source toolkit for peer-to-peer protocols like blockchains, chat rooms,
BitTorrent swarms, and content-addressed stores.

## Install

```bash
pip install chaincraft
```

Ed25519 is optional: `pip install "chaincraft[ed25519]"`. The node is
`python3 -m chaincraft.node`. Default listen is `0.0.0.0:9735`.

## Hello World

Two TCP nodes in one process. A listens on `9735`, B on `9736`, B dials A and
gossips `app.hello`.

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
a.close()
b.close()
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

Specification and the Rust and TypeScript implementations live in the
[monorepo](https://github.com/jose-compu/chaincraft-monorepo).
