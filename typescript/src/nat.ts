/** Pedagogical NAT traversal — SPEC/features/discovery-nat.md. */

import { isValidAddress } from './discovery.ts';
import { ProtocolError } from './errors.ts';

export const APP_NAT = 'app.nat';
export const PUNCH_HEX = '00';

const MAGIC = 0x2112a442;
const MAGIC_B = [0x21, 0x12, 0xa4, 0x42] as const;
const BINDING_REQUEST = 0x0001;
const BINDING_SUCCESS = 0x0101;
const XOR_MAPPED = 0x0020;

export interface CodecResult {
  readonly ok: boolean;
  readonly packet: string;
}

export interface ParsedBinding {
  readonly ok: boolean;
  readonly host: string;
  readonly port: number;
}

export interface Punch {
  readonly ok: boolean;
  readonly datagram: string;
  readonly addr: string;
}

export interface RelayOut {
  readonly ok: boolean;
  readonly message: NatMessage | null;
}

export interface HandleOut {
  readonly ok: boolean;
  readonly action: string;
  readonly addr: string;
  readonly reply: NatMessage | null;
}

export interface NatMessage {
  readonly from: string;
  readonly nat: string;
  readonly relay?: string;
  readonly target: string;
}

const FAIL_PARSE: ParsedBinding = { ok: false, host: '', port: 0 };

export function bindingRequest(txid: string): CodecResult {
  const raw = txidBytes(txid);
  if (!raw) return { ok: false, packet: '' };
  return { ok: true, packet: toHex(header(BINDING_REQUEST, 0, raw)) };
}

export function bindingSuccess(txid: string, host: string, port: unknown): CodecResult {
  const raw = txidBytes(txid);
  const octets = ipv4(host);
  if (!raw || !octets || !isPort(port)) return { ok: false, packet: '' };
  const value = xorMapped(octets, port);
  const attr = new Uint8Array(4 + value.length);
  writeU16(attr, 0, XOR_MAPPED);
  writeU16(attr, 2, value.length);
  attr.set(value, 4);
  const head = header(BINDING_SUCCESS, attr.length, raw);
  const packet = new Uint8Array(head.length + attr.length);
  packet.set(head, 0);
  packet.set(attr, head.length);
  return { ok: true, packet: toHex(packet) };
}

export function parseBindingResponse(packet: unknown, txid: unknown): ParsedBinding {
  const raw = unhex(packet);
  const ident = txidBytes(typeof txid === 'string' ? txid : '');
  if (!raw || !ident || raw.length < 20) return { ...FAIL_PARSE };
  const msgType = readU16(raw, 0);
  const length = readU16(raw, 2);
  const magic = readU32(raw, 4);
  if (msgType !== BINDING_SUCCESS || magic !== MAGIC || !same(raw.subarray(8, 20), ident)) {
    return { ...FAIL_PARSE };
  }
  if (length !== raw.length - 20) return { ...FAIL_PARSE };
  const end = 20 + length;
  let offset = 20;
  let found: Uint8Array | null = null;
  while (offset + 4 <= end) {
    const atype = readU16(raw, offset);
    const alen = readU16(raw, offset + 2);
    offset += 4;
    if (offset + alen > end) return { ...FAIL_PARSE };
    const value = raw.subarray(offset, offset + alen);
    offset += alen;
    const pad = (4 - (alen % 4)) % 4;
    if (offset + pad > end) return { ...FAIL_PARSE };
    offset += pad;
    if (atype === XOR_MAPPED && found === null) found = value;
  }
  if (offset !== end || !found || found.length !== 8 || found[0] !== 0 || found[1] !== 1) {
    return { ...FAIL_PARSE };
  }
  const port = readU16(found, 2) ^ 0x2112;
  if (port < 1 || port > 65535) return { ...FAIL_PARSE };
  const host = [0, 1, 2, 3].map((i) => String((found as Uint8Array)[4 + i]! ^ MAGIC_B[i]!)).join('.');
  return { ok: true, host, port };
}

export class NatTraversal {
  readonly #listen: string;
  readonly #fixed: string | null;
  #mapped: string | null;
  readonly #relay: string | null;
  #armed = false;
  readonly #opened: string[] = [];
  readonly #seen: string[] = [];

  constructor(listen: string, external: string | null = null, relay: string | null = null) {
    if (!isValidAddress(listen)) throw new ProtocolError('invalid listen address');
    if (external !== null && !isValidAddress(external)) throw new ProtocolError('invalid external address');
    if (relay !== null && !isValidAddress(relay)) throw new ProtocolError('invalid relay address');
    this.#listen = listen;
    this.#fixed = external;
    this.#mapped = external;
    this.#relay = relay;
  }

  armed(): boolean {
    return this.#armed;
  }

  arm(transport: string): boolean {
    this.#armed = transport === 'udp';
    return this.#armed;
  }

  externalAddress(): string {
    return this.#mapped ?? '';
  }

  advertise(): string {
    return this.#mapped ?? this.#listen;
  }

  observeStun(packet: unknown, txid: unknown): boolean {
    if (!this.#armed || this.#fixed !== null) return false;
    const parsed = parseBindingResponse(packet, txid);
    if (!parsed.ok) return false;
    const mapped = `${parsed.host}:${parsed.port}`;
    if (!isValidAddress(mapped)) return false;
    this.#mapped = mapped;
    return true;
  }

  punch(peer: unknown): Punch {
    if (typeof peer !== 'string' || !this.#armed || !isValidAddress(peer) || this.#ours(peer)) {
      return { ok: false, datagram: '', addr: '' };
    }
    return { ok: true, datagram: PUNCH_HEX, addr: peer };
  }

  observePunch(datagram: unknown, origin: unknown): boolean {
    if (!this.#armed || datagram !== PUNCH_HEX) return false;
    if (typeof origin !== 'string' || !isValidAddress(origin) || this.#ours(origin)) return false;
    if (!this.#opened.includes(origin)) this.#opened.push(origin);
    return true;
  }

  opened(): string[] {
    return [...this.#opened];
  }

  relayRequest(target: unknown): RelayOut {
    if (
      !this.#armed ||
      this.#relay === null ||
      typeof target !== 'string' ||
      !isValidAddress(target) ||
      this.#ours(target) ||
      target === this.#relay ||
      this.#opened.includes(target)
    ) {
      return { ok: false, message: null };
    }
    return {
      ok: true,
      message: {
        from: this.advertise(),
        nat: 'request',
        relay: this.#relay,
        target,
      },
    };
  }

  handle(message: unknown): HandleOut {
    const fail: HandleOut = { ok: false, action: '', addr: '', reply: null };
    if (!this.#armed || !isRecord(message)) return fail;
    const kind = message['nat'];
    const origin = message['from'];
    const target = message['target'];
    if (kind !== 'request' && kind !== 'response') return fail;
    if (typeof origin !== 'string' || typeof target !== 'string') return fail;
    if (!isValidAddress(origin) || !isValidAddress(target) || this.#ours(origin)) return fail;
    let relay = '';
    if (kind === 'request') {
      const field = message['relay'];
      if (typeof field !== 'string' || !isValidAddress(field)) return fail;
      relay = field;
    }
    const ident = kind === 'request' ? `request|${origin}|${target}|${relay}` : `response|${origin}|${target}`;
    if (this.#seen.includes(ident)) return fail;
    if (target === this.#listen || target === this.advertise()) {
      this.#seen.push(ident);
      if (kind === 'request') {
        return {
          ok: true,
          action: 'punch',
          addr: origin,
          reply: { from: this.advertise(), nat: 'response', target: origin },
        };
      }
      if (!this.#opened.includes(origin)) this.#opened.push(origin);
      return { ok: true, action: 'punch', addr: origin, reply: null };
    }
    if (kind === 'request' && (relay === this.#listen || relay === this.advertise())) {
      this.#seen.push(ident);
      return {
        ok: true,
        action: 'forward',
        addr: target,
        reply: { from: origin, nat: 'request', relay, target },
      };
    }
    return fail;
  }

  #ours(addr: string): boolean {
    return addr === this.#listen || addr === this.advertise();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPort(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 65535;
}

function txidBytes(value: string): Uint8Array | null {
  const raw = unhex(value);
  if (!raw || raw.length !== 12) return null;
  return raw;
}

function unhex(value: unknown): Uint8Array | null {
  if (typeof value !== 'string' || value.length % 2 !== 0) return null;
  const out = new Uint8Array(value.length / 2);
  for (let i = 0; i < out.length; i += 1) {
    const hi = hexVal(value.charCodeAt(i * 2));
    const lo = hexVal(value.charCodeAt(i * 2 + 1));
    if (hi === null || lo === null) return null;
    out[i] = (hi << 4) | lo;
  }
  return out;
}

function hexVal(code: number): number | null {
  if (code >= 48 && code <= 57) return code - 48;
  if (code >= 97 && code <= 102) return code - 97 + 10;
  return null;
}

function toHex(bytes: Uint8Array): string {
  let out = '';
  for (const byte of bytes) out += byte.toString(16).padStart(2, '0');
  return out;
}

function header(msgType: number, length: number, txid: Uint8Array): Uint8Array {
  const out = new Uint8Array(20);
  writeU16(out, 0, msgType);
  writeU16(out, 2, length);
  writeU32(out, 4, MAGIC);
  out.set(txid, 8);
  return out;
}

function xorMapped(octets: number[], port: number): Uint8Array {
  const xport = port ^ 0x2112;
  return new Uint8Array([
    0,
    1,
    (xport >> 8) & 0xff,
    xport & 0xff,
    octets[0]! ^ MAGIC_B[0],
    octets[1]! ^ MAGIC_B[1],
    octets[2]! ^ MAGIC_B[2],
    octets[3]! ^ MAGIC_B[3],
  ]);
}

function ipv4(host: string): number[] | null {
  const labels = host.split('.');
  if (labels.length !== 4) return null;
  const octets: number[] = [];
  for (const label of labels) {
    if (!/^[0-9]+$/.test(label) || (label.length > 1 && label.startsWith('0'))) return null;
    const value = Number(label);
    if (value > 255) return null;
    octets.push(value);
  }
  return octets;
}

function writeU16(buf: Uint8Array, offset: number, value: number): void {
  buf[offset] = (value >> 8) & 0xff;
  buf[offset + 1] = value & 0xff;
}

function writeU32(buf: Uint8Array, offset: number, value: number): void {
  buf[offset] = (value >>> 24) & 0xff;
  buf[offset + 1] = (value >>> 16) & 0xff;
  buf[offset + 2] = (value >>> 8) & 0xff;
  buf[offset + 3] = value & 0xff;
}

function readU16(buf: Uint8Array, offset: number): number {
  return ((buf[offset] ?? 0) << 8) | (buf[offset + 1] ?? 0);
}

function readU32(buf: Uint8Array, offset: number): number {
  return (
    ((buf[offset] ?? 0) * 0x1000000) +
    ((buf[offset + 1] ?? 0) << 16) +
    ((buf[offset + 2] ?? 0) << 8) +
    (buf[offset + 3] ?? 0)
  );
}

function same(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  for (let i = 0; i < left.length; i += 1) {
    if (left[i] !== right[i]) return false;
  }
  return true;
}
