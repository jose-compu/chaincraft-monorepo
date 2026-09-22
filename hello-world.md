# Hello World

Interactive version: open [`index.html`](index.html) in this folder, or the published site.

This walks through a gossiped message on Chaincraft 1.0.0. The control channel is JSON lines. Python, Rust, and TypeScript speak the same commands.

## Commands

Each stdin line is one JSON object.

| `cmd` | Fields | Effect |
|---|---|---|
| `connect` | `addr` | Dial `host:port` and complete `ctl.hello` |
| `send` | `type`, `data` | Broadcast an application envelope |
| `ids` | — | List payload ids this process has sent |
| `quit` | — | Close the node |

The node prints events on stdout: `ready` (with `addr` and `impl`), `connected`, `sent` (with `id`), `ids`, `error`.

## Steps

1. Clone the monorepo and install one core:

   ```bash
   git clone https://github.com/jose-compu/chaincraft-monorepo.git
   cd chaincraft-monorepo/python
   pip install -e ".[dev]"
   ```

2. Start two nodes. The Rust binary is the same protocol.

   ```bash
   # Terminal 1
   python -m chaincraft_core.node

   # Terminal 2
   cd ../rust && cargo run --bin node
   ```

3. Read `addr` from the first `ready` event. On terminal 2:

   ```json
   {"cmd":"connect","addr":"127.0.0.1:PORT"}
   ```

4. On terminal 1, send:

   ```json
   {"cmd":"send","type":"app.hello","data":{"message":"Hello, Chaincraft!"}}
   ```

   The `sent.id` is SHA-256 of the canonical payload. The peer records the same digest.

5. Press Ctrl-C, or send `{"cmd":"quit"}`, to stop each node.

A TypeScript node is `npm run node` from `typescript/`. The live 3×3 check is `python3 conformance/runner/run_interop.py` from the repository root.
