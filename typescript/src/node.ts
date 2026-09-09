/**
 * Minimal TCP mesh node — SPEC/wire-v1.md §4, §5, §7, §8.
 *
 * JSON-lines on stdin/stdout; the live interop runner drives this process.
 */

import * as net from 'node:net';
import * as readline from 'node:readline';

import {
  type JsonValue,
  Deduplicator,
  Envelope,
  FrameReader,
  IMPL,
  ProtocolError,
  control,
  encodeFrame,
} from './index.ts';

type Event = Record<string, unknown>;

interface Peer {
  socket: net.Socket;
  addr: string;
  impl?: string;
}

function emit(event: Event): void {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

class Mesh {
  readonly impl: string;
  readonly dedup = new Deduplicator();
  readonly peers: Peer[] = [];
  readonly received: Array<{ id: string; type: string; data: JsonValue }> = [];
  listenAddr = '';
  private server: net.Server | undefined;

  constructor(impl: string = IMPL) {
    this.impl = impl;
  }

  start(host = '127.0.0.1', port = 0): Promise<string> {
    return new Promise((resolve, reject) => {
      const server = net.createServer((socket) => this.addPeer(socket));
      server.on('error', reject);
      server.listen(port, host, () => {
        const addr = server.address();
        if (addr === null || typeof addr === 'string') {
          reject(new Error('expected a TCP address'));
          return;
        }
        this.listenAddr = `${addr.address}:${addr.port}`;
        this.server = server;
        resolve(this.listenAddr);
      });
    });
  }

  connect(addr: string): Promise<void> {
    const [host, port] = splitAddr(addr);
    return new Promise((resolve, reject) => {
      const socket = net.connect({ host, port }, () => {
        this.addPeer(socket, addr);
        resolve();
      });
      socket.once('error', reject);
    });
  }

  broadcast(typeName: string, data: JsonValue): string {
    const env = Envelope.build(typeName, data);
    const fresh = this.dedup.shouldProcess(env);
    if (fresh) {
      this.received.push({ id: env.id, type: env.type, data: env.data });
      for (const peer of this.peers) {
        this.write(peer, env);
      }
    }
    return env.id;
  }

  ids(): string[] {
    return this.received.map((item) => item.id);
  }

  close(): void {
    this.server?.close();
    for (const peer of this.peers) {
      peer.socket.destroy();
    }
  }

  private addPeer(socket: net.Socket, addr?: string): void {
    const remote = socket.remoteAddress ?? 'unknown';
    const remotePort = socket.remotePort ?? 0;
    const peer: Peer = { socket, addr: addr ?? `${remote}:${remotePort}` };
    this.peers.push(peer);
    this.write(peer, control.hello(this.impl, { listen: this.listenAddr }));
    const reader = new FrameReader();
    socket.on('data', (chunk: Buffer) => {
      try {
        for (const body of reader.feed(new Uint8Array(chunk))) {
          this.handle(peer, body);
        }
      } catch (error) {
        emit({ event: 'error', message: String(error), addr: peer.addr });
        socket.destroy();
      }
    });
    socket.on('error', (error) => {
      emit({ event: 'error', message: error.message, addr: peer.addr });
    });
    socket.on('close', () => {
      const index = this.peers.indexOf(peer);
      if (index >= 0) this.peers.splice(index, 1);
    });
  }

  private write(peer: Peer, env: Envelope): void {
    peer.socket.write(Buffer.from(encodeFrame(env.toBytes())));
  }

  private handle(peer: Peer, body: Uint8Array): void {
    const env = Envelope.parse(body);
    if (env.isControl()) {
      if (env.type === control.HELLO) {
        const hello = control.parseHello(env);
        peer.impl = hello.impl;
        emit({ event: 'hello', peer: hello.impl, addr: peer.addr });
      }
      return;
    }
    if (!this.dedup.shouldProcess(env)) return;
    this.received.push({ id: env.id, type: env.type, data: env.data });
    emit({ event: 'received', id: env.id, type: env.type, data: env.data });
    if (this.dedup.shouldRelay(env)) {
      for (const other of this.peers) {
        if (other === peer) continue;
        try {
          this.write(other, env);
        } catch {
          // drop a broken peer; close will remove it
        }
      }
    }
  }
}

function splitAddr(addr: string): [string, number] {
  const idx = addr.lastIndexOf(':');
  return [addr.slice(0, idx), Number(addr.slice(idx + 1))];
}

const mesh = new Mesh();
await mesh.start();
emit({ event: 'ready', addr: mesh.listenAddr, impl: IMPL });

const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  const cmd = JSON.parse(line) as Record<string, any>;
  try {
    if (cmd['cmd'] === 'connect') {
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
