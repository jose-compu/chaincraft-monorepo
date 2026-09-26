# @chaincraft/core

TypeScript implementation of the Chaincraft wire protocol and object semantics.

## Install

```bash
npm install @chaincraft/core
```

The unscoped npm name `chaincraft` belongs to another project. This package is
`@chaincraft/core`, alongside the `chaincraft` crate and the `chaincraft` Python
package.

## Example

Assumes `@chaincraft/core` is installed.

```ts
import { Envelope, encodeFrame } from "@chaincraft/core";

const env = Envelope.build("app.counter", { by: "alice", delta: 1 });
const frame = encodeFrame(env.toBytes());
```

Specification and the other implementations live in the
[monorepo](https://github.com/jose-compu/chaincraft-monorepo).
