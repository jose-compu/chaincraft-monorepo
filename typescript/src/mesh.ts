/**
 * TCP mesh — SPEC/wire-v1.md §4, §5, §7, §8.
 *
 * Application protocols attach via `onApp`, not by editing this module.
 */

import * as dns from 'node:dns/promises';
import * as net from 'node:net';

import { type JsonValue } from './canonical.ts';
import * as control from './control.ts';
import { Deduplicator } from './dedup.ts';
import { isConnectAllowed, isResolvedIpAllowed } from './discovery.ts';
import { Envelope } from './envelope.ts';
import { ProtocolError } from './errors.ts';
import { IMPL } from './features.ts';
import { FrameReader, encodeFrame } from './framing.ts';

export const MAX_PEERS = 16;
export const MAX_RECEIVED = 4096;
export const CONNECT_TIMEOUT_MS = 5000;
export const NODE_MAX_FRAME = 262_144;

export type MeshEvent = Record<string, unknown>;
export type AppHandler = (typeName: string, data: JsonValue) => void;
export type LinkHandler = (addr: string, typeName: string, data: JsonValue) => void;

interface Peer {
  socket: net.Socket;
  addr: string;
  impl?: string;
}

export class Mesh {
  readonly impl: string;
  readonly dedup = new Deduplicator();
  readonly peers: Peer[] = [];
  readonly received: Array<{ id: string; type: string; data: JsonValue }> = [];
  listenAddr = '';
  onApp: AppHandler = () => undefined;
  onLink: LinkHandler = () => undefined;
  private readonly onEvent: (event: MeshEvent) => void;
  private server: net.Server | undefined;

  constructor(impl: string = IMPL, onEvent: (event: MeshEvent) => void = () => undefined) {
    this.impl = impl;
    this.onEvent = onEvent;
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

  async connect(addr: string): Promise<void> {
    if (!isConnectAllowed(addr)) throw new Error('address not allowed');
    const [host, port] = splitAddr(addr);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      throw new Error('address not allowed');
    }
    const lookup = await dns.lookup(host, { family: 4 });
    if (!isResolvedIpAllowed(lookup.address)) throw new Error('address not allowed');
    await new Promise<void>((resolve, reject) => {
      const socket = net.connect({ host: lookup.address, port }, () => {
        socket.setTimeout(0);
        this.addPeer(socket, addr);
        resolve();
      });
      socket.setTimeout(CONNECT_TIMEOUT_MS, () => {
        socket.destroy();
        reject(new Error('connect timeout'));
      });
      socket.once('error', reject);
    });
  }

  broadcast(typeName: string, data: JsonValue): string {
    const env = Envelope.build(typeName, data);
    if (env.isControl()) throw new ProtocolError('broadcast is the gossip path');
    const fresh = this.dedup.shouldProcess(env);
    if (fresh) {
      this.record(env);
      for (const peer of this.peers) {
        this.write(peer, env);
      }
      this.onApp(typeName, data);
    }
    return env.id;
  }

  send(addr: string, typeName: string, data: JsonValue): string {
    const env = Envelope.build(typeName, data);
    if (!env.isControl()) throw new ProtocolError('send is the control path');
    const peer = this.peers.find((item) => item.addr === addr);
    if (peer === undefined) throw new ProtocolError('no such link');
    this.write(peer, env);
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

  private record(env: Envelope): void {
    if (this.received.length >= MAX_RECEIVED) this.received.shift();
    this.received.push({ id: env.id, type: env.type, data: env.data });
  }

  private addPeer(socket: net.Socket, addr?: string): void {
    if (this.peers.length >= MAX_PEERS) {
      socket.destroy();
      return;
    }
    const remote = socket.remoteAddress ?? 'unknown';
    const remotePort = socket.remotePort ?? 0;
    const peer: Peer = { socket, addr: addr ?? `${remote}:${remotePort}` };
    this.peers.push(peer);
    this.write(peer, control.hello(this.impl, { listen: this.listenAddr }));
    const reader = new FrameReader(NODE_MAX_FRAME);
    socket.on('data', (chunk: Buffer) => {
      try {
        for (const body of reader.feed(new Uint8Array(chunk))) {
          this.handle(peer, body);
        }
      } catch (error) {
        this.onEvent({ event: 'error', message: String(error), addr: peer.addr });
        socket.destroy();
      }
    });
    socket.on('error', (error) => {
      this.onEvent({ event: 'error', message: error.message, addr: peer.addr });
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
    if (env.type.startsWith('ctl.')) {
      if (env.type === control.HELLO) {
        const hello = control.parseHello(env);
        peer.impl = hello.impl;
        this.onEvent({ event: 'hello', peer: hello.impl, addr: peer.addr });
      }
      return;
    }
    if (env.isControl()) {
      this.onLink(peer.addr, env.type, env.data);
      return;
    }
    if (!this.dedup.shouldProcess(env)) return;
    this.record(env);
    this.onEvent({ event: 'received', id: env.id, type: env.type, data: env.data });
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
    this.onApp(env.type, env.data);
  }
}

function splitAddr(addr: string): [string, number] {
  const idx = addr.lastIndexOf(':');
  return [addr.slice(0, idx), Number(addr.slice(idx + 1))];
}
