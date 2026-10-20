/** PeerJS ids, broker options, and an in-memory cross-scheme relay.
 *
 * SPEC/features/channel-peer.md. Signaling is an HTTP GET. The relay does not
 * open an ICE data channel. This module does not import node:net.
 */

import type { JsonValue } from './canonical.ts';
import { isPeerId, parseAddress } from './channel.ts';
import { Envelope } from './envelope.ts';
import { ProtocolError } from './errors.ts';

export const DEFAULT_PEER_ORIGIN = 'https://dechess-org-peerjs.vercel.app';
export const PEER_KEY = 'peerjs';

const RELAY = new Set(['udp', 'mailto', 'webrtc', 'forum', 'pipe']);

export interface PeerOptions {
  host: string;
  port: number;
  path: string;
  secure: boolean;
  key: string;
}

export interface RelayItem {
  id: string;
  type: string;
  from: string;
}

export { isPeerId };

export function parsePeerIdBody(text: string): string | undefined {
  const ident = text.trim();
  if (!isPeerId(ident)) return undefined;
  return ident;
}

export function peerOptions(origin: string = DEFAULT_PEER_ORIGIN): PeerOptions {
  const parsed = new URL(origin);
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new Error('peer origin must be http or https');
  }
  const secure = parsed.protocol === 'https:';
  const port = parsed.port ? Number(parsed.port) : secure ? 443 : 80;
  if (!parsed.hostname) throw new Error('peer origin must be http or https');
  return { host: parsed.hostname, port, path: '/', secure, key: PEER_KEY };
}

export async function fetchPeerId(origin: string = DEFAULT_PEER_ORIGIN): Promise<string> {
  const response = await fetch(`${origin.replace(/\/$/, '')}/peerjs/id`, {
    headers: { Accept: 'text/plain' },
  });
  if (!response.ok) throw new Error(`peer id fetch failed: ${response.status}`);
  const ident = parsePeerIdBody(await response.text());
  if (ident === undefined) throw new Error('invalid peer id');
  return ident;
}

export class EnvelopeRelay {
  private readonly order: string[] = [];
  private readonly inbox = new Map<string, RelayItem[]>();
  private readonly seen = new Set<string>();

  join(addr: string): boolean {
    const parsed = parseAddress(addr);
    if (!parsed.ok || !RELAY.has(parsed.scheme)) return false;
    if (this.inbox.has(parsed.canonical)) return false;
    this.order.push(parsed.canonical);
    this.inbox.set(parsed.canonical, []);
    return true;
  }

  publish(src: string, typeName: string, data: JsonValue): string | undefined {
    const parsed = parseAddress(src);
    if (!parsed.ok || !this.inbox.has(parsed.canonical)) return undefined;
    let env: Envelope;
    try {
      env = Envelope.build(typeName, data, { ts: 0 });
    } catch (error) {
      if (error instanceof ProtocolError) return undefined;
      throw error;
    }
    if (this.seen.has(env.id)) return env.id;
    this.seen.add(env.id);
    const item: RelayItem = { id: env.id, type: env.type, from: parsed.canonical };
    for (const member of this.order) {
      if (member === parsed.canonical) continue;
      const box = this.inbox.get(member);
      if (box) box.push({ ...item });
    }
    return env.id;
  }

  take(addr: string): RelayItem[] {
    const parsed = parseAddress(addr);
    if (!parsed.ok) return [];
    const box = this.inbox.get(parsed.canonical);
    if (!box) return [];
    const out = box.slice();
    box.length = 0;
    return out;
  }
}
