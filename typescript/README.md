# @chaincraft/core

TypeScript implementation of the Chaincraft wire protocol and object semantics.
Release **[1.1.0](https://www.npmjs.com/package/@chaincraft/core)** on npm.

Open-source toolkit for peer-to-peer protocols like blockchains, chat rooms,
BitTorrent swarms, and content-addressed stores.

## Install

```bash
npm install @chaincraft/core
npm install --global @chaincraft/core
```

The node binary is `chaincraft-ts-node`. Default listen is `0.0.0.0:9735`.

The unscoped npm name `chaincraft` belongs to another project. This package is
`@chaincraft/core`, alongside the `chaincraft` crate and the `chaincraft` Python
package.

## Hello World

Two TCP nodes in one process. A listens on `9735`, B on `9736`, B dials A and
gossips `app.hello`. Save as `hello.mjs` and run `node hello.mjs`.

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
Each mesh keeps at most 256 peers.

Specification and the other implementations live in the
[monorepo](https://github.com/jose-compu/chaincraft-monorepo).
