#!/usr/bin/env node
/**
 * BitTorrent mesh client — Swarm on top of the Level 0 mesh.
 *
 * Driven by conformance/runner/run_bittorrent.py.
 */

import * as readline from 'node:readline';

import { type JsonValue, BitTorrentClient, IMPL, ProtocolError } from './index.ts';
import { Mesh, parseListen } from './mesh.ts';

const MAX_STDIN_LINE = 1_048_576;

function emit(event: Record<string, unknown>): void {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

const mesh = new Mesh(IMPL, emit);
const client = new BitTorrentClient((typeName, data) => mesh.broadcast(typeName, data));
mesh.onApp = (typeName, data) => client.onApp(typeName, data);
const listen = parseListen(process.argv[2]);
await mesh.start(listen.host, listen.port);
emit({ event: 'ready', addr: mesh.listenAddr, impl: IMPL });

const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  if (line.length > MAX_STDIN_LINE) {
    emit({ event: 'error', message: 'line too long' });
    continue;
  }
  if (!line.trim()) continue;
  const cmd = JSON.parse(line) as Record<string, any>;
  try {
    const btEvent = client.handleCommand(cmd);
    if (btEvent !== undefined) {
      emit(btEvent);
    } else if (cmd['cmd'] === 'connect') {
      await mesh.connect(cmd['addr']);
      emit({ event: 'connected', addr: cmd['addr'] });
    } else if (cmd['cmd'] === 'send') {
      const id = mesh.broadcast(cmd['type'], cmd['data'] as JsonValue);
      emit({ event: 'sent', id });
    } else if (cmd['cmd'] === 'ids') {
      emit({ event: 'ids', ids: mesh.ids() });
    } else if (cmd['cmd'] === 'quit') {
      break;
    } else {
      emit({ event: 'error', message: `unknown cmd ${cmd['cmd']}` });
    }
  } catch (error) {
    const message = error instanceof ProtocolError ? error.message : String(error);
    emit({ event: 'error', message });
  }
}
mesh.close();
