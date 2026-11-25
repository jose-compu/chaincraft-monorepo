/** Local peer strike list — SPEC/features/discovery-ban.md. */

import { isValidAddress } from './discovery.ts';

export const DEFAULT_STRIKE_LIMIT = 3;
export const DEFAULT_BAN_TTL_MS = 60_000;
export const MAX_TRACKED = 64;

const STRIKE_REASONS = new Set(['digest_flood', 'malformed']);
const VALID_REASONS = new Set([...STRIKE_REASONS, 'invalid_address']);

export interface ClassifyResult {
  action: 'ignore' | 'deliver' | 'drop';
  reason: string | null;
}

export function classifyInbound(
  typeName: string,
  solicited: boolean,
  duplicate: boolean,
  addressOk: boolean,
): ClassifyResult {
  if (typeName === 'ctl.peers' && !solicited) {
    return { action: 'ignore', reason: null };
  }
  if (typeName.startsWith('ctl.') || typeName.startsWith('link.')) {
    return { action: 'deliver', reason: null };
  }
  if (!addressOk) {
    return { action: 'drop', reason: 'invalid_address' };
  }
  if (duplicate) {
    return { action: 'drop', reason: 'digest_flood' };
  }
  return { action: 'deliver', reason: null };
}

interface Entry {
  strikes: number;
  bannedAt: number | null;
}

export interface BanPeerState {
  peer: string;
  strikes: number;
  banned_at: number | null;
}

export interface BanSetState {
  tracked: BanPeerState[];
  banned: string[];
  size: number;
}

export class BanSet {
  readonly strikeLimit: number;
  readonly banTtlMs: number;
  private readonly order: string[] = [];
  private readonly peers = new Map<string, Entry>();

  constructor(strikeLimit = DEFAULT_STRIKE_LIMIT, banTtlMs = DEFAULT_BAN_TTL_MS) {
    if (!Number.isInteger(strikeLimit) || strikeLimit < 1) {
      throw new Error('strike_limit must be a positive integer');
    }
    if (!Number.isInteger(banTtlMs) || banTtlMs < 1) {
      throw new Error('ban_ttl_ms must be a positive integer');
    }
    this.strikeLimit = strikeLimit;
    this.banTtlMs = banTtlMs;
  }

  private expirePeer(peer: string, nowMs: number): void {
    const entry = this.peers.get(peer);
    if (entry === undefined || entry.bannedAt === null) return;
    if (nowMs - entry.bannedAt > this.banTtlMs) {
      this.removePeer(peer);
    }
  }

  private expireAll(nowMs: number): void {
    for (const peer of [...this.order]) {
      this.expirePeer(peer, nowMs);
    }
  }

  private isActiveBan(entry: Entry, nowMs: number): boolean {
    if (entry.bannedAt === null) return false;
    return nowMs - entry.bannedAt <= this.banTtlMs;
  }

  private removePeer(peer: string): void {
    this.peers.delete(peer);
    const index = this.order.indexOf(peer);
    if (index >= 0) this.order.splice(index, 1);
  }

  private evictIfNeeded(): boolean {
    if (this.order.length < MAX_TRACKED) return true;
    for (const peer of this.order) {
      const entry = this.peers.get(peer);
      if (entry !== undefined && entry.bannedAt === null) {
        this.removePeer(peer);
        return true;
      }
    }
    return false;
  }

  private ensurePeer(peer: string): Entry | undefined {
    const existing = this.peers.get(peer);
    if (existing !== undefined) return existing;
    if (!this.evictIfNeeded()) return undefined;
    const entry: Entry = { strikes: 0, bannedAt: null };
    this.order.push(peer);
    this.peers.set(peer, entry);
    return entry;
  }

  note(peer: string, reason: string, nowMs: number): 'ignored' | 'strike' | 'banned' {
    if (!Number.isInteger(nowMs) || nowMs < 0) return 'ignored';
    if (!isValidAddress(peer)) return 'ignored';
    if (!VALID_REASONS.has(reason)) return 'ignored';

    this.expireAll(nowMs);
    const prior = this.peers.get(peer);
    if (prior !== undefined && this.isActiveBan(prior, nowMs)) return 'banned';

    if (reason === 'invalid_address') {
      const entry = this.ensurePeer(peer);
      if (entry === undefined) return 'ignored';
      entry.strikes = this.strikeLimit;
      entry.bannedAt = nowMs;
      return 'banned';
    }

    const entry = this.ensurePeer(peer);
    if (entry === undefined) return 'ignored';
    entry.strikes += 1;
    if (entry.strikes >= this.strikeLimit) {
      entry.bannedAt = nowMs;
      return 'banned';
    }
    return 'strike';
  }

  isBanned(peer: string, nowMs: number): boolean {
    this.expirePeer(peer, nowMs);
    const entry = this.peers.get(peer);
    if (entry === undefined) return false;
    return this.isActiveBan(entry, nowMs);
  }

  strikes(peer: string): number {
    return this.peers.get(peer)?.strikes ?? 0;
  }

  banned(nowMs: number): string[] {
    this.expireAll(nowMs);
    const out: string[] = [];
    for (const [peer, entry] of this.peers) {
      if (this.isActiveBan(entry, nowMs)) out.push(peer);
    }
    out.sort();
    return out;
  }

  state(nowMs: number): BanSetState {
    this.expireAll(nowMs);
    const tracked: BanPeerState[] = [];
    for (const peer of this.order) {
      const entry = this.peers.get(peer);
      if (entry === undefined) continue;
      tracked.push({
        peer,
        strikes: entry.strikes,
        banned_at: entry.bannedAt,
      });
    }
    return {
      tracked,
      banned: this.banned(nowMs),
      size: this.order.length,
    };
  }
}
