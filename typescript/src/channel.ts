/** Address URIs and an in-process loop channel — SPEC/features/wire-channel.md. */

import { isConnectAllowed as hostPortConnectAllowed, isValidAddress } from './discovery.ts';

export const MAX_LOOP_BYTES = 64;

export interface ParsedAddress {
  ok: boolean;
  scheme: string;
  canonical: string;
  cap: string;
}

const FAIL: ParsedAddress = { ok: false, scheme: '', canonical: '', cap: '' };
const AUTHORITY = new Set(['tcp', 'udp']);
const COLON = ['mailto', 'webrtc', 'forum', 'loop'] as const;
const HEX = /^[0-9a-f]+$/;
const HEX64 = /^[0-9a-f]{64}$/;
const LOCAL = /^[A-Za-z0-9._+-]{1,64}$/;
const LABEL = /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/;
const THREAD = /^[A-Za-z0-9._-]{1,64}$/;

function ok(scheme: string, canonical: string): ParsedAddress {
  return { ok: true, scheme, canonical, cap: scheme };
}

export function parseAddress(raw: string): ParsedAddress {
  if (!raw) return { ...FAIL };
  const authority = raw.indexOf('://');
  if (authority >= 0) {
    const scheme = raw.slice(0, authority);
    const rest = raw.slice(authority + 3);
    if (!AUTHORITY.has(scheme)) return { ...FAIL };
    if (/[@/?#]/.test(rest)) return { ...FAIL };
    if (!isValidAddress(rest)) return { ...FAIL };
    return ok(scheme, `${scheme}://${rest}`);
  }
  for (const scheme of COLON) {
    const prefix = `${scheme}:`;
    if (raw.startsWith(prefix)) return parseColon(scheme, raw.slice(prefix.length));
  }
  if (isValidAddress(raw)) return ok('tcp', `tcp://${raw}`);
  return { ...FAIL };
}

export function isConnectAllowed(raw: string): boolean {
  const parsed = parseAddress(raw);
  if (!parsed.ok) return false;
  if (parsed.scheme === 'tcp' || parsed.scheme === 'udp') {
    const rest = parsed.canonical.split('://')[1] ?? '';
    return hostPortConnectAllowed(rest);
  }
  return true;
}

function parseColon(scheme: string, rest: string): ParsedAddress {
  if (scheme === 'mailto') {
    const parts = rest.split('@');
    if (parts.length !== 2) return { ...FAIL };
    const local = parts[0] ?? '';
    const domain = parts[1] ?? '';
    if (!LOCAL.test(local) || !isValidAddress(`${domain}:1`)) return { ...FAIL };
    return ok(scheme, `mailto:${rest}`);
  }
  if (scheme === 'webrtc') {
    if (!HEX64.test(rest)) return { ...FAIL };
    return ok(scheme, `webrtc:${rest}`);
  }
  if (scheme === 'forum') {
    const parts = rest.split(':');
    if (parts.length !== 2) return { ...FAIL };
    const profile = parts[0] ?? '';
    const thread = parts[1] ?? '';
    if (!LABEL.test(profile) || !THREAD.test(thread)) return { ...FAIL };
    return ok(scheme, `forum:${rest}`);
  }
  if (scheme === 'loop') {
    if (!LABEL.test(rest)) return { ...FAIL };
    return ok(scheme, `loop:${rest}`);
  }
  return { ...FAIL };
}

function validPayload(data: string): boolean {
  if (data.length < 2 || data.length % 2 !== 0) return false;
  if (!HEX.test(data)) return false;
  const n = data.length / 2;
  return n >= 1 && n <= MAX_LOOP_BYTES;
}

export interface InboxItem {
  from: string;
  data: string;
}

export class LoopBus {
  readonly bound = new Map<string, LoopChannel>();
}

export class LoopChannel {
  readonly bus: LoopBus;
  listenAddr = '';
  private readonly items: InboxItem[] = [];

  constructor(bus: LoopBus) {
    this.bus = bus;
  }

  inbox(): InboxItem[] {
    return this.items.map((item) => ({ ...item }));
  }

  listen(addr: string): boolean {
    const parsed = parseAddress(addr);
    if (!parsed.ok || parsed.scheme !== 'loop' || this.listenAddr) return false;
    if (this.bus.bound.has(parsed.canonical)) return false;
    this.listenAddr = parsed.canonical;
    this.bus.bound.set(parsed.canonical, this);
    return true;
  }

  dial(addr: string): boolean {
    const parsed = parseAddress(addr);
    if (!parsed.ok || parsed.scheme !== 'loop') return false;
    return this.bus.bound.has(parsed.canonical);
  }

  send(addr: string, data: string): boolean {
    const parsed = parseAddress(addr);
    if (!parsed.ok || parsed.scheme !== 'loop' || !validPayload(data)) return false;
    const dest = this.bus.bound.get(parsed.canonical);
    if (dest === undefined) return false;
    dest.items.push({ from: this.listenAddr, data });
    return true;
  }

  recv(): InboxItem[] {
    return this.items.splice(0, this.items.length);
  }

  close(): void {
    if (this.listenAddr) {
      if (this.bus.bound.get(this.listenAddr) === this) {
        this.bus.bound.delete(this.listenAddr);
      }
      this.listenAddr = '';
    }
    this.items.length = 0;
  }
}
