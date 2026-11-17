# @chaincraft/core

TypeScript implementation of the Chaincraft wire protocol, object semantics, and
Level 2 stack (consensus, ledgers, BitTorrent, channels). Same observable
behaviour as the Python `chaincraft` package and the Rust `chaincraft` crate.
Release **[1.7.0](https://www.npmjs.com/package/@chaincraft/core/v/1.7.0)** on npm.
1.7.0 adds `consensus.poet` (Proof of Elapsed Time on a shared Sloth seed).
46 of 47 registry features implemented plus the UDP framing exemption.

Open-source toolkit for peer-to-peer protocols like blockchains, chat rooms,
BitTorrent swarms, and content-addressed stores.

Node **20+**, ESM only (`"type": "module"`). The default entry and `Mesh` use
`node:net`; browser consumers can use the `@chaincraft/core/browser` entry.
Raw UDP is the one registry exemption (browsers have no UDP socket). The
unscoped npm name `chaincraft` belongs to another project.

## Install

```bash
npm install @chaincraft/core
npm install --global @chaincraft/core
```

Global binaries: `chaincraft-ts-node` (mesh CLI) and `chaincraft-ts-bt-node`
(BitTorrent client on the same mesh). Default listen is `0.0.0.0:9735`.

Without a global install:

```bash
npx chaincraft-ts-node
# or
node node_modules/@chaincraft/core/dist/node.js
```

## Browser

`@chaincraft/core/browser` does not import `node:net`. `Mesh` stays on the Node
entry. A page asks the PeerJS broker for an id and passes `peerOptions()` to
`Peer`. The default broker is `https://dechess-org-peerjs.vercel.app`.

```js
import { fetchPeerId, peerOptions } from "@chaincraft/core/browser";

const id = await fetchPeerId();
const peer = new Peer(id, peerOptions());
```

The data channel is the caller's. `EnvelopeRelay` is the in-memory stand-in
used by the conformance vectors.

## Envelope

`id` is SHA-256 of the canonical payload. Keys are sorted. There is no floating
point on the wire.

```ts
import { Envelope, encodeFrame } from "@chaincraft/core";

const env = Envelope.build("app.hello", { message: "Hello, Chaincraft!" });
const frame = encodeFrame(env.toBytes());
console.log(env.id, frame.length);
```

## Object

A prototype implements `receive`. Attach it to `Mesh.onApp`. Reject with
`isValid`. Consensus objects override `addMessage` and the snapshot.

```ts
import { BaseSharedObject, type JsonValue } from "@chaincraft/core";

class Hello extends BaseSharedObject {
  lines: string[] = [];
  receive(message: JsonValue): void {
    const text = (message as { message?: string }).message ?? "";
    this.lines.push(text);
    console.log("Received:", text);
  }
}
```

## Hello World (TCP)

Two nodes in one process. A listens on `9735`, B on `9736`, B dials A and
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

## CLI

JSON lines on stdin. Events on stdout.

```bash
chaincraft-ts-node
chaincraft-ts-node 127.0.0.1:9737
```

| `cmd` | Fields | Effect |
|---|---|---|
| `connect` | `addr` | Dial `host:port`, complete `ctl.hello` |
| `send` | `type`, `data` | Gossip an application envelope |
| `ids` | — | Payload ids this process has recorded |
| `quit` | — | Stop |

Three languages on one loopback mesh: Python holds `9735`, Rust `9736`,
TypeScript `9737`.

```bash
python3 -m chaincraft.node
chaincraft-node 127.0.0.1:9736
chaincraft-ts-node 127.0.0.1:9737
```

On terminals 2 and 3:

```json
{"cmd":"connect","addr":"127.0.0.1:9735"}
```

On terminal 1:

```json
{"cmd":"send","type":"app.hello","data":{"message":"Hello, Chaincraft!"}}
```

`sent.id` is the same digest on every language. `{"cmd":"ids"}` lists it.
BitTorrent is a separate process: `chaincraft-ts-bt-node`.

## Network

Further local nodes take unused ports and `connect`. Remote hosts dial this
machine's unicast IPv4 or DNS name on 9735. Default bind is `0.0.0.0:9735`;
loopback Hello World still uses `127.0.0.1:9735`.

`connect` allows loopback, RFC1918, public unicast IPv4, `localhost`, `.local`,
and ordinary DNS names. Unspecified (`0.0.0.0`), link-local, multicast, and
reserved addresses are refused. One mesh process keeps at most 256 live peers.

## Library

| Area | Entry |
|---|---|
| Wire | `Envelope`, `encodeFrame`, `canonicalJson`, `sign` / `verify` |
| Objects | `BaseSharedObject`, `ObjectRegistry`, `StateMemento` |
| Mesh | `Mesh`, `parseListen` |
| Gossip apps | `PubSub`, `Stream`, `BitTorrentClient` |
| Chain | `ProofOfWork`, `ProofOfStake`, `PBFT`, `BalanceLedger`, `UtxoLedger`, `Mempool` |
| Discovery | `AddressBook`, `NatTraversal`, `parseAddress` |

Specification and the Python and Rust implementations live in the
[monorepo](https://github.com/jose-compu/chaincraft-monorepo).
