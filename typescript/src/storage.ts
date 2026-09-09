/** Persistent message store — SPEC/features/storage-persistent.md. */

export const DEFAULT_CAPACITY = 8;

const HEX64 = /^[0-9a-f]{64}$/;

export function isValidId(value: string): boolean {
  return HEX64.test(value);
}

export class MessageStore {
  readonly capacity: number;
  private readonly entries: Map<string, string>;

  constructor(capacity: number = DEFAULT_CAPACITY) {
    if (!Number.isSafeInteger(capacity) || capacity < 1) {
      throw new RangeError('capacity must be >= 1');
    }
    this.capacity = capacity;
    this.entries = new Map();
  }

  get size(): number {
    return this.entries.size;
  }

  ids(): string[] {
    return [...this.entries.keys()];
  }

  put(id: string, body: string): boolean {
    if (!isValidId(id) || body.length === 0) return false;
    if (this.entries.has(id)) {
      this.entries.set(id, body);
      return false;
    }
    if (this.entries.size >= this.capacity) {
      const oldest = this.entries.keys().next().value;
      if (oldest !== undefined) this.entries.delete(oldest);
    }
    this.entries.set(id, body);
    return true;
  }

  get(id: string): { body: string; found: boolean } {
    const body = this.entries.get(id);
    if (body === undefined) return { body: '', found: false };
    return { body, found: true };
  }

  remove(id: string): boolean {
    return this.entries.delete(id);
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
    return true;
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
