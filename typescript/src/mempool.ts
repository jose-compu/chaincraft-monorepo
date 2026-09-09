/** Transaction pool — SPEC/features/mempool-basic.md. */

import type { JsonValue } from './canonical.ts';
import { merkleDigest } from './object.ts';

export const DEFAULT_CAPACITY = 8;
export const DEFAULT_MIN_FEE = 0;
export const DEFAULT_TTL_MS = 60_000;
export const DEFAULT_MAX_PER_SENDER = 0;
export const DEFAULT_RBF_MIN_INCREASE = 1;

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

export function transactionId(fee: number, nonce: number, payload: string, sender: string): string {
  return merkleDigest({ fee, nonce, payload, sender });
}

function parseTx(
  message: JsonValue,
): { id: string; sender: string; fee: number; nonce: number; payload: string } | undefined {
  const record = asRecord(message);
  if (record === undefined) return undefined;
  const sender = record['sender'];
  const payload = record['payload'];
  const fee = record['fee'];
  const nonce = record['nonce'];
  if (typeof sender !== 'string' || sender.length === 0) return undefined;
  if (typeof payload !== 'string' || payload.length === 0) return undefined;
  if (!isInt(fee) || fee < 0) return undefined;
  if (!isInt(nonce) || nonce < 0) return undefined;
  return { id: transactionId(fee, nonce, payload, sender), sender, fee, nonce, payload };
}

export interface InsertResult {
  accepted: boolean;
  evicted: string;
  expired: number;
  replaced: string;
}

interface Entry {
  fee: number;
  nonce: number;
  payload: string;
  receivedAt: number;
  sender: string;
}

export class Mempool {
  readonly capacity: number;
  readonly minFee: number;
  readonly ttlMs: number;
  readonly maxPerSender: number;
  readonly rbfMinIncrease: number;
  private readonly entries: Map<string, Entry>;
  private readonly slots: Map<string, string>;

  constructor(
    capacity: number = DEFAULT_CAPACITY,
    minFee: number = DEFAULT_MIN_FEE,
    ttlMs: number = DEFAULT_TTL_MS,
    maxPerSender: number = DEFAULT_MAX_PER_SENDER,
    rbfMinIncrease: number = DEFAULT_RBF_MIN_INCREASE,
  ) {
    if (!Number.isSafeInteger(capacity) || capacity < 1) {
      throw new RangeError('capacity must be >= 1');
    }
    if (!Number.isSafeInteger(minFee) || minFee < 0) {
      throw new RangeError('min_fee must be >= 0');
    }
    if (!Number.isSafeInteger(ttlMs) || ttlMs < 0) {
      throw new RangeError('ttl_ms must be >= 0');
    }
    if (!Number.isSafeInteger(maxPerSender) || maxPerSender < 0) {
      throw new RangeError('max_per_sender must be >= 0');
    }
    if (!Number.isSafeInteger(rbfMinIncrease) || rbfMinIncrease < 1) {
      throw new RangeError('rbf_min_increase must be >= 1');
    }
    this.capacity = capacity;
    this.minFee = minFee;
    this.ttlMs = ttlMs;
    this.maxPerSender = maxPerSender;
    this.rbfMinIncrease = rbfMinIncrease;
    this.entries = new Map();
    this.slots = new Map();
  }

  get size(): number {
    return this.entries.size;
  }

  ids(): string[] {
    return [...this.entries.keys()];
  }

  insert(message: JsonValue, nowMs: number): InsertResult {
    const expired = this.sweep(nowMs);
    const parsed = parseTx(message);
    if (parsed === undefined) return this.result(false, '', '', expired);
    if (this.entries.has(parsed.id)) return this.result(false, '', '', expired);
    if (parsed.fee < this.minFee) return this.result(false, '', '', expired);
    let replaced = '';
    const slot = `${parsed.sender}\0${parsed.nonce}`;
    const existingId = this.slots.get(slot);
    if (existingId !== undefined) {
      const existing = this.entries.get(existingId);
      if (existing === undefined || parsed.fee < existing.fee + this.rbfMinIncrease) {
        return this.result(false, '', '', expired);
      }
      this.discard(existingId);
      replaced = existingId;
    }
    if (replaced === '' && this.maxPerSender > 0 && this.senderCount(parsed.sender) >= this.maxPerSender) {
      return this.result(false, '', '', expired);
    }
    let evicted = '';
    if (this.entries.size >= this.capacity) {
      const victim = this.lowestFee();
      const stored = victim === undefined ? undefined : this.entries.get(victim);
      if (stored === undefined || stored.fee >= parsed.fee) {
        return this.result(false, replaced, '', expired);
      }
      this.discard(victim!);
      evicted = victim!;
    }
    this.entries.set(parsed.id, {
      fee: parsed.fee,
      nonce: parsed.nonce,
      payload: parsed.payload,
      receivedAt: nowMs,
      sender: parsed.sender,
    });
    this.slots.set(slot, parsed.id);
    return this.result(true, replaced, evicted, expired);
  }

  remove(id: string): boolean {
    return this.discard(id);
  }

  sweep(nowMs: number): number {
    if (this.ttlMs === 0) return 0;
    const expired: string[] = [];
    for (const [id, entry] of this.entries) {
      if (nowMs - entry.receivedAt > this.ttlMs) expired.push(id);
    }
    for (const id of expired) this.discard(id);
    return expired.length;
  }

  private result(accepted: boolean, replaced: string, evicted: string, expired: number): InsertResult {
    return { accepted, evicted, expired, replaced };
  }

  private discard(id: string): boolean {
    const entry = this.entries.get(id);
    if (entry === undefined) return false;
    this.entries.delete(id);
    this.slots.delete(`${entry.sender}\0${entry.nonce}`);
    return true;
  }

  private senderCount(sender: string): number {
    let count = 0;
    for (const entry of this.entries.values()) {
      if (entry.sender === sender) count += 1;
    }
    return count;
  }

  private lowestFee(): string | undefined {
    let bestId: string | undefined;
    let bestFee: number | undefined;
    for (const [id, entry] of this.entries) {
      if (bestFee === undefined || entry.fee < bestFee) {
        bestId = id;
        bestFee = entry.fee;
      }
    }
    return bestId;
  }
}
