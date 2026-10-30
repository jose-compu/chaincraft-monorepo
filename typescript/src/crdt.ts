/** Last-write-wins key-value CRDT — SPEC/features/protocol-crdt-kv.md. */

import { type JsonValue, MAX_SAFE_INT, compareCodePoints } from './canonical.ts';
import { BaseSharedObject } from './object.ts';

export const MAX_KEYS = 32;
export const MAX_VALUE = 256;

const NAME = /^[A-Za-z0-9._-]{1,64}$/;

interface Register {
  ts: number;
  writer: string;
  value: string;
  deleted: boolean;
}

type Op = {
  key: string;
  ts: number;
  writer: string;
  value: string;
  deleted: boolean;
};

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message;
}

export interface CrdtKvState {
  keys: Array<{
    deleted: boolean;
    key: string;
    ts: number;
    value: string;
    writer: string;
  }>;
}

export class CrdtKv extends BaseSharedObject {
  private readonly keys = new Map<string, Register>();

  override isValid(message: JsonValue): boolean {
    return this.parse(message) !== undefined;
  }

  override receive(message: JsonValue): void {
    const parsed = this.parse(message);
    if (parsed === undefined) return;
    const current = this.keys.get(parsed.key);
    if (current === undefined) {
      this.keys.set(parsed.key, {
        ts: parsed.ts,
        writer: parsed.writer,
        value: parsed.value,
        deleted: parsed.deleted,
      });
      return;
    }
    if (parsed.ts === current.ts && parsed.writer === current.writer) return;
    if (
      parsed.ts > current.ts ||
      (parsed.ts === current.ts && compareCodePoints(parsed.writer, current.writer) < 0)
    ) {
      this.keys.set(parsed.key, {
        ts: parsed.ts,
        writer: parsed.writer,
        value: parsed.value,
        deleted: parsed.deleted,
      });
    }
  }

  state(): CrdtKvState {
    const names = Array.from(this.keys.keys()).sort(compareCodePoints);
    return {
      keys: names.map((key) => {
        const item = this.keys.get(key)!;
        return {
          deleted: item.deleted,
          key,
          ts: item.ts,
          value: item.value,
          writer: item.writer,
        };
      }),
    };
  }

  private parse(message: JsonValue): Op | undefined {
    const obj = asRecord(message);
    if (obj === undefined || obj['app'] !== 'crdt') return undefined;
    const op = obj['op'];
    const key = obj['key'];
    const writer = obj['writer'];
    const ts = obj['ts'];
    if (op !== 'set' && op !== 'del') return undefined;
    if (typeof key !== 'string' || !NAME.test(key)) return undefined;
    if (typeof writer !== 'string' || !NAME.test(writer)) return undefined;
    if (!isInt(ts) || ts < 0 || ts > MAX_SAFE_INT) return undefined;
    const deleted = op === 'del';
    let value = '';
    if (!deleted) {
      const text = obj['value'];
      if (typeof text !== 'string') return undefined;
      const scalars = Array.from(text).length;
      if (scalars < 1 || scalars > MAX_VALUE) return undefined;
      value = text;
    }
    const current = this.keys.get(key);
    if (current === undefined) {
      if (this.keys.size >= MAX_KEYS) return undefined;
      return { key, ts, writer, value, deleted };
    }
    if (current.ts === ts && current.writer === writer) {
      if (current.deleted !== deleted || current.value !== value) return undefined;
    }
    return { key, ts, writer, value, deleted };
  }
}
