/** Persistent message store — SPEC/features/storage-persistent.md, storage-index.md. */

import { type JsonValue, MAX_SAFE_INT, MIN_SAFE_INT } from './canonical.ts';
import { Envelope } from './envelope.ts';
import { ProtocolError } from './errors.ts';

export const DEFAULT_CAPACITY = 8;
const MAX_REGISTRATIONS = 8;

const HEX64 = /^[0-9a-f]{64}$/;
const TYPE_RE = /^[a-z0-9._-]{1,64}$/;
const FIELD_RE = /^[A-Za-z0-9._-]{1,64}$/;

type RegKey = `${string}\0${string}`;
type IndexKey = `${string}\0${string}\0${string}`;

export function isValidId(value: string): boolean {
  return HEX64.test(value);
}

function regKey(type: string, field: string): RegKey {
  return `${type}\0${field}`;
}

function indexKey(type: string, field: string, encoded: string): IndexKey {
  return `${type}\0${field}\0${encoded}`;
}

function isWireInt(value: JsonValue): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= MIN_SAFE_INT && value <= MAX_SAFE_INT;
}

function encodeValue(value: JsonValue): string | undefined {
  if (typeof value === 'string') return `s:${value}`;
  if (typeof value === 'boolean') return `b:${value ? 1 : 0}`;
  if (isWireInt(value)) return `i:${value}`;
  return undefined;
}

function indexValues(raw: JsonValue): JsonValue[] {
  if (typeof raw === 'string' || typeof raw === 'boolean') return [raw];
  if (isWireInt(raw)) return [raw];
  if (Array.isArray(raw)) {
    const out: JsonValue[] = [];
    const seen = new Set<string>();
    for (const item of raw) {
      const enc = encodeValue(item);
      if (enc === undefined) continue;
      if (seen.has(enc)) continue;
      seen.add(enc);
      out.push(item);
    }
    return out;
  }
  return [];
}

export class MessageStore {
  readonly capacity: number;
  private readonly entries: Map<string, string>;
  private readonly registrations: Set<RegKey>;
  private readonly postings: Map<IndexKey, string[]>;
  private readonly idKeys: Map<string, Set<IndexKey>>;

  constructor(capacity: number = DEFAULT_CAPACITY) {
    if (!Number.isSafeInteger(capacity) || capacity < 1) {
      throw new RangeError('capacity must be >= 1');
    }
    this.capacity = capacity;
    this.entries = new Map();
    this.registrations = new Set();
    this.postings = new Map();
    this.idKeys = new Map();
  }

  get size(): number {
    return this.entries.size;
  }

  ids(): string[] {
    return [...this.entries.keys()];
  }

  register(type: string, field: string): boolean {
    if (!TYPE_RE.test(type) || !FIELD_RE.test(field)) return false;
    const key = regKey(type, field);
    if (this.registrations.has(key)) return true;
    if (this.registrations.size >= MAX_REGISTRATIONS) return false;
    this.registrations.add(key);
    return true;
  }

  query(type: string, field: string, value: JsonValue): string[] {
    const enc = encodeValue(value);
    if (enc === undefined) return [];
    if (!this.registrations.has(regKey(type, field))) return [];
    return [...(this.postings.get(indexKey(type, field, enc)) ?? [])];
  }

  put(id: string, body: string): boolean {
    if (!isValidId(id) || body.length === 0) return false;
    if (this.entries.has(id)) {
      this.unindexId(id);
      this.entries.set(id, body);
      this.indexBody(id, body);
      return false;
    }
    if (this.entries.size >= this.capacity) {
      const oldest = this.entries.keys().next().value;
      if (oldest !== undefined) {
        this.unindexId(oldest);
        this.entries.delete(oldest);
      }
    }
    this.entries.set(id, body);
    this.indexBody(id, body);
    return true;
  }

  get(id: string): { body: string; found: boolean } {
    const body = this.entries.get(id);
    if (body === undefined) return { body: '', found: false };
    return { body, found: true };
  }

  remove(id: string): boolean {
    if (!this.entries.delete(id)) return false;
    this.unindexId(id);
    return true;
  }

  dump(): { entries: { body: string; id: string }[]; v: number } {
    const entries: { body: string; id: string }[] = [];
    for (const [id, body] of this.entries) entries.push({ body, id });
    return { entries, v: 1 };
  }

  load(snapshot: unknown): boolean {
    const parsed = parseSnapshot(snapshot, this.capacity);
    if (parsed === undefined) return false;
    this.entries.clear();
    for (const [id, body] of parsed) this.entries.set(id, body);
    this.rebuildIndex();
    return true;
  }

  private rebuildIndex(): void {
    this.postings.clear();
    this.idKeys.clear();
    for (const [id, body] of this.entries) this.indexBody(id, body);
  }

  private unindexId(id: string): void {
    const keys = this.idKeys.get(id);
    if (keys === undefined) return;
    this.idKeys.delete(id);
    for (const key of keys) {
      const bucket = this.postings.get(key);
      if (bucket === undefined) continue;
      const next = bucket.filter((entry) => entry !== id);
      if (next.length === 0) this.postings.delete(key);
      else this.postings.set(key, next);
    }
  }

  private indexBody(id: string, body: string): void {
    let env: Envelope;
    try {
      env = Envelope.parse(body);
    } catch (e) {
      if (e instanceof ProtocolError) return;
      throw e;
    }
    if (env.data === null || typeof env.data !== 'object' || Array.isArray(env.data)) return;
    const data = env.data as Record<string, JsonValue>;
    const keysForId = new Set<IndexKey>();
    for (const reg of this.registrations) {
      const [type, field] = reg.split('\0');
      if (type === undefined || field === undefined) continue;
      if (env.type !== type) continue;
      const raw = data[field];
      if (raw === undefined) continue;
      for (const value of indexValues(raw)) {
        const enc = encodeValue(value);
        if (enc === undefined) continue;
        const idx = indexKey(type, field, enc);
        keysForId.add(idx);
        const bucket = this.postings.get(idx) ?? [];
        if (!bucket.includes(id)) bucket.push(id);
        this.postings.set(idx, bucket);
      }
    }
    if (keysForId.size > 0) this.idKeys.set(id, keysForId);
  }
}

function parseSnapshot(
  snapshot: unknown,
  capacity: number,
): Map<string, string> | undefined {
  if (snapshot === null || typeof snapshot !== 'object' || Array.isArray(snapshot)) {
    return undefined;
  }
  const record = snapshot as Record<string, unknown>;
  if (record['v'] !== 1) return undefined;
  const raw = record['entries'];
  if (!Array.isArray(raw) || raw.length > capacity) return undefined;
  const out = new Map<string, string>();
  for (const item of raw) {
    if (item === null || typeof item !== 'object' || Array.isArray(item)) return undefined;
    const entry = item as Record<string, unknown>;
    const id = entry['id'];
    const body = entry['body'];
    if (typeof id !== 'string' || !isValidId(id) || typeof body !== 'string' || body.length === 0) {
      return undefined;
    }
    if (out.has(id)) return undefined;
    out.set(id, body);
  }
  return out;
}