/** Channel adapters — SPEC/features/channel-adapters.md. */

import dgram from 'node:dgram';

import { parseAddress } from './channel.ts';
import { MAX_UDP_BYTES, decodeDatagram } from './framing.ts';

export const MAX_UDP_PAYLOAD = MAX_UDP_BYTES;
export const MAX_MAIL_BYTES = 4096;
export const MAX_WEBRTC_BYTES = MAX_UDP_BYTES;
export const MAX_FORUM_BYTES = 4096;

export interface InboxItem {
  data: string;
  from: string;
}

const HEX = /^[0-9a-f]+$/;

export class AdapterBus {
  readonly scheme: string;
  readonly maxBytes: number;
  readonly bound = new Map<string, AdapterChannel>();

  constructor(scheme: string, maxBytes: number) {
    this.scheme = scheme;
    this.maxBytes = maxBytes;
  }

  static udp(): AdapterBus {
    return new AdapterBus('udp', MAX_UDP_PAYLOAD);
  }

  static mail(): AdapterBus {
    return new AdapterBus('mailto', MAX_MAIL_BYTES);
  }

  static webrtc(): AdapterBus {
    return new AdapterBus('webrtc', MAX_WEBRTC_BYTES);
  }

  static forum(): AdapterBus {
    return new AdapterBus('forum', MAX_FORUM_BYTES);
  }
}

export class AdapterChannel {
  listenAddr = '';
  readonly #inbox: InboxItem[] = [];

  constructor(private readonly bus: AdapterBus) {}

  listen(addr: string): boolean {
    const parsed = parseAddress(addr);
    if (!parsed.ok || parsed.scheme !== this.bus.scheme || this.listenAddr !== '') return false;
    if (this.bus.bound.has(parsed.canonical)) return false;
    this.listenAddr = parsed.canonical;
    this.bus.bound.set(parsed.canonical, this);
    return true;
  }

  dial(addr: string): boolean {
    const parsed = parseAddress(addr);
    if (!parsed.ok || parsed.scheme !== this.bus.scheme) return false;
    return this.bus.bound.has(parsed.canonical);
  }

  send(addr: string, data: string): boolean {
    const parsed = parseAddress(addr);
    if (!parsed.ok || parsed.scheme !== this.bus.scheme || !validPayload(data, this.bus.maxBytes)) {
      return false;
    }
    const dest = this.bus.bound.get(parsed.canonical);
    if (dest === undefined) return false;
    dest.#inbox.push({ data, from: this.listenAddr });
    return true;
  }

  recv(): InboxItem[] {
    return this.#inbox.splice(0, this.#inbox.length);
  }

  inbox(): InboxItem[] {
    return this.#inbox.slice();
  }

  close(): void {
    if (this.listenAddr !== '') {
      if (this.bus.bound.get(this.listenAddr) === this) this.bus.bound.delete(this.listenAddr);
      this.listenAddr = '';
    }
    this.#inbox.splice(0, this.#inbox.length);
  }
}

function validPayload(data: string, maxBytes: number): boolean {
  if (data.length < 2 || data.length % 2 !== 0 || !HEX.test(data)) return false;
  const n = data.length / 2;
  return n >= 1 && n <= maxBytes;
}

export class UdpLink {
  private constructor(
    private readonly socket: dgram.Socket,
    readonly hostPort: string,
  ) {}

  static bind(): Promise<UdpLink> {
    return new Promise((resolve, reject) => {
      const socket = dgram.createSocket('udp4');
      socket.once('error', reject);
      socket.bind(0, '127.0.0.1', () => {
        const addr = socket.address();
        resolve(new UdpLink(socket, `${addr.address}:${addr.port}`));
      });
    });
  }

  send(hostPort: string, body: Uint8Array): Promise<void> {
    decodeDatagram(body);
    const idx = hostPort.lastIndexOf(':');
    const host = hostPort.slice(0, idx);
    const port = Number(hostPort.slice(idx + 1));
    return new Promise((resolve, reject) => {
      this.socket.send(Buffer.from(body), port, host, (error) => {
        if (error) reject(error);
        else resolve();
      });
    });
  }

  recv(): Promise<{ from: string; body: Uint8Array }> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('udp timeout')), 2000);
      this.socket.once('message', (msg, rinfo) => {
        clearTimeout(timer);
        const body = decodeDatagram(new Uint8Array(msg));
        resolve({ from: `${rinfo.address}:${rinfo.port}`, body });
      });
    });
  }

  close(): Promise<void> {
    return new Promise((resolve) => {
      this.socket.close(() => resolve());
    });
  }
}
