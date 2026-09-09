/**
 * Conformance fixture objects — SPEC/semantics-v1.md §8.
 *
 * These exist only so replay vectors are portable: every implementation feeds
 * pipeline.json through objects behaving exactly like these. They are not part
 * of the shipped API, which is why they live under test/.
 */

import type { JsonValue } from '../src/canonical.ts';
import { StateMemento } from '../src/memento.ts';
import { BaseSharedObject, merkleDigest } from '../src/object.ts';
import { ObjectRegistry } from '../src/pipeline.ts';

/** Integers only. Booleans must not pass, matching §8.1. */
function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

export interface CounterState {
  seq: number;
  total: number;
  head: string;
}

/** Merkelized, chain-shaped — §8.1. */
export class Counter extends BaseSharedObject {
  seq = 0;
  total = 0;
  head = '';

  override isValid(message: JsonValue): boolean {
    const record = asRecord(message);
    if (record === undefined) return false;
    const delta = record['delta'];
    const seq = record['seq'];
    if (!isInt(delta) || !isInt(seq)) return false;
    if (delta < -100 || delta > 100) return false;
    return seq === this.seq + 1;
  }

  override addMessage(
    message: JsonValue,
    frontierState?: StateMemento | undefined,
  ): StateMemento | undefined {
    const record = message as Record<string, JsonValue>;
    const previous = this.head;
    this.total += record['delta'] as number;
    this.seq = record['seq'] as number;
    this.head = merkleDigest({
      previous_digest: previous,
      seq: this.seq,
      total: this.total,
      v: 1,
    });
    return StateMemento.normalize(this.head, frontierState?.frontierDigests ?? []);
  }

  override emitStateMemento(): StateMemento {
    return StateMemento.normalize(this.head, []);
  }

  override getStateDigests(): string[] {
    return this.head ? [this.head] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): CounterState {
    return { seq: this.seq, total: this.total, head: this.head };
  }
}

export interface MirrorState {
  count: number;
  last_frontier: string[];
}

/**
 * Records what the pipeline threaded into it — §8.2.
 *
 * Returns nothing from addMessage, which exercises the emitStateMemento()
 * branch of the threading rule in §3 step 4.
 */
export class Mirror extends BaseSharedObject {
  count = 0;
  lastFrontier: string[] = [];

  override isValid(message: JsonValue): boolean {
    const record = asRecord(message);
    return !(record !== undefined && record['reject_mirror'] === true);
  }

  override addMessage(
    _message: JsonValue,
    frontierState?: StateMemento | undefined,
  ): StateMemento | undefined {
    this.count += 1;
    this.lastFrontier = [...(frontierState?.frontierDigests ?? [])];
    return undefined;
  }

  override emitStateMemento(): StateMemento {
    return StateMemento.normalize('', this.lastFrontier);
  }

  state(): MirrorState {
    return { count: this.count, last_frontier: [...this.lastFrontier] };
  }
}

/** Registration order is counter then mirror — §8.3. */
export function buildRegistry(): ObjectRegistry {
  return new ObjectRegistry().register('counter', new Counter()).register(
    'mirror',
    new Mirror(),
  );
}

export interface Snapshot {
  counter: CounterState;
  mirror: MirrorState;
}

/** Observable state, in the shape recorded by replay vectors — §8.4. */
export function snapshot(registry: ObjectRegistry): Snapshot {
  return {
    counter: (registry.get('counter') as Counter).state(),
    mirror: (registry.get('mirror') as Mirror).state(),
  };
}
