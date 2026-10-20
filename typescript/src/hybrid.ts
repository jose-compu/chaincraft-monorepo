/** One mesh, one channel per peer — SPEC/features/channel-hybrid.md. */

import type { JsonValue } from './canonical.ts';
import { parseAddress } from './channel.ts';
import { Envelope } from './envelope.ts';
import { ProtocolError } from './errors.ts';

export const HOP_CAP: Readonly<Record<string, number>> = {
  tcp: 262144,
  udp: 65507,
  webrtc: 65507,
  pipe: 65507,
  mailto: 4096,
  forum: 4096,
  loop: 64,
};

export interface HybridItem {
  id: string;
  type: string;
  from: string;
}

export function helloCaps(udp: boolean): string[] {
  const caps = ['digest-sync', 'gossip'];
  if (udp) caps.push('udp');
  return caps.sort();
}

export class LinkMesh {
  private readonly order: string[] = [];
  private readonly scheme = new Map<string, string>();
  private readonly inbox = new Map<string, HybridItem[]>();
  private readonly seen = new Set<string>();

  join(addr: string): boolean {
    const parsed = parseAddress(addr);
    if (!parsed.ok || !(parsed.scheme in HOP_CAP)) return false;
    if (this.inbox.has(parsed.canonical)) return false;
    this.order.push(parsed.canonical);
    this.scheme.set(parsed.canonical, parsed.scheme);
    this.inbox.set(parsed.canonical, []);
    return true;
  }

  gossip(src: string, typeName: string, data: JsonValue): string | undefined {
    return this.send(src, undefined, typeName, data, true);
  }

  direct(src: string, dst: string, typeName: string, data: JsonValue): string | undefined {
    return this.send(src, dst, typeName, data, false);
  }

  take(addr: string): HybridItem[] {
    const canonical = canonicalOf(addr);
    if (canonical === undefined) return [];
    const box = this.inbox.get(canonical);
    if (box === undefined) return [];
    const out = box.slice();
    box.length = 0;
    return out;
  }

  private send(
    src: string,
    dst: string | undefined,
    typeName: string,
    data: JsonValue,
    gossip: boolean,
  ): string | undefined {
    const source = canonicalOf(src);
    if (source === undefined || !this.inbox.has(source)) return undefined;
    let target: string | undefined;
    if (!gossip) {
      target = dst === undefined ? undefined : canonicalOf(dst);
      if (target === undefined || !this.inbox.has(target)) return undefined;
    }
    let env: Envelope;
    try {
      env = Envelope.build(typeName, data, { ts: 0 });
    } catch (error) {
      if (error instanceof ProtocolError) return undefined;
      throw error;
    }
    if (gossip && env.isControl()) return undefined;
    if (!gossip && !env.isControl()) return undefined;
    if (this.seen.has(env.id)) return env.id;
    this.seen.add(env.id);
    const size = env.toBytes().length;
    const item: HybridItem = { id: env.id, type: env.type, from: source };
    if (gossip) {
      for (const member of this.order) {
        if (member === source) continue;
        const scheme = this.scheme.get(member) ?? '';
        const cap = HOP_CAP[scheme] ?? 0;
        if (size <= cap) this.inbox.get(member)?.push({ ...item });
      }
    } else if (target !== undefined) {
      const scheme = this.scheme.get(target) ?? '';
      const cap = HOP_CAP[scheme] ?? 0;
      if (size <= cap) this.inbox.get(target)?.push({ ...item });
    }
    return env.id;
  }
}

function canonicalOf(addr: string): string | undefined {
  const parsed = parseAddress(addr);
  if (!parsed.ok) return undefined;
  return parsed.canonical;
}
