/** Fee policy — SPEC/features/fees-policy.md. */

import { type JsonValue, compareCodePoints } from './canonical.ts';

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

export function select(candidates: readonly JsonValue[], limit: number): string[] {
  if (!Number.isSafeInteger(limit) || limit < 1) {
    throw new RangeError('limit must be >= 1');
  }
  const seen = new Set<string>();
  const ranked: { id: string; fee: number }[] = [];
  for (const item of candidates) {
    const record = asRecord(item);
    if (record === undefined) continue;
    const id = record['id'];
    const fee = record['fee'];
    if (typeof id !== 'string' || id.length === 0) continue;
    if (!isInt(fee) || fee < 0) continue;
    if (seen.has(id)) continue;
    seen.add(id);
    ranked.push({ id, fee });
  }
  ranked.sort((left, right) => {
    if (left.fee !== right.fee) return right.fee - left.fee;
    return compareCodePoints(left.id, right.id);
  });
  return ranked.slice(0, limit).map((row) => row.id);
}

export function charge(fee: number, base: number): { burned: number; charged: number; tip: number } {
  if (!Number.isSafeInteger(fee) || fee < 0 || !Number.isSafeInteger(base) || base < 0) {
    throw new RangeError('fee and base must be integers >= 0');
  }
  const burned = fee < base ? fee : base;
  return { burned, charged: fee, tip: fee - burned };
}

export function estimate(fees: readonly number[]): number {
  const values: number[] = [];
  for (const item of fees) {
    if (!Number.isSafeInteger(item) || item < 0) {
      throw new RangeError('fees must be integers >= 0');
    }
    values.push(item);
  }
  if (values.length === 0) return 0;
  values.sort((a, b) => a - b);
  const mid = Math.trunc(values.length / 2);
  if (values.length % 2 === 1) return values[mid]!;
  return Math.trunc((values[mid - 1]! + values[mid]!) / 2);
}

export function nextBaseFee(base: number, parentCount: number, target: number): number {
  if (!Number.isSafeInteger(base) || base < 0) throw new RangeError('base must be >= 0');
  if (!Number.isSafeInteger(parentCount) || parentCount < 0) {
    throw new RangeError('parent_count must be >= 0');
  }
  if (!Number.isSafeInteger(target) || target < 1) throw new RangeError('target must be >= 1');
  const denom = target * 8;
  const next =
    parentCount >= target
      ? base + Math.trunc((base * (parentCount - target)) / denom)
      : base - Math.trunc((base * (target - parentCount)) / denom);
  return next < 1 ? 1 : next;
}
