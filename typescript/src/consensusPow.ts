/** Proof-of-work object — SPEC/features/consensus-pow.md. */

import type { JsonValue } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';

export const DEFAULT_DIFFICULTY = 2;

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

export function blockId(
  height: number,
  miner: string,
  nonce: number,
  parent: string,
  payload: string,
): string {
  return merkleDigest({ height, miner, nonce, parent, payload });
}

export function meetsWork(digest: string, difficulty: number): boolean {
  return digest.length >= difficulty && digest.startsWith('0'.repeat(difficulty));
}

interface Stored {
  height: number;
  miner: string;
  nonce: number;
  parent: string;
  payload: string;
}

export class ProofOfWork extends BaseSharedObject {
  readonly difficulty: number;
  private readonly blocks = new Map<string, Stored>();
  private readonly order: string[] = [];

  constructor(difficulty: number = DEFAULT_DIFFICULTY) {
    super();
    if (!Number.isSafeInteger(difficulty) || difficulty < 1 || difficulty > 64) {
      throw new RangeError('difficulty must be in 1..64');
    }
    this.difficulty = difficulty;
  }

  override isValid(message: JsonValue): boolean {
    return this.parse(message) !== undefined;
  }

  override addMessage(
    message: JsonValue,
    _frontierState?: StateMemento | undefined,
  ): StateMemento | undefined {
    const parsed = this.parse(message);
    if (parsed === undefined) return this.emitStateMemento();
    this.blocks.set(parsed.digest, parsed.record);
    this.order.push(parsed.digest);
    return this.emitStateMemento();
  }

  override emitStateMemento(): StateMemento {
    const tip = this.tip();
    return StateMemento.normalize(
      merkleDigest({ height: tip.height, tip: tip.id, v: 1 }),
      [],
    );
  }

  override getStateDigests(): string[] {
    const tip = this.tip();
    return tip.id ? [tip.id] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): { blocks: string[]; canonical: string[]; height: number; tip: string } {
    const tip = this.tip();
    return {
      blocks: [...this.order],
      canonical: this.canonical(tip.id),
      height: tip.height,
      tip: tip.id,
    };
  }

  private canonical(tip: string): string[] {
    const chain: string[] = [];
    let cursor = tip;
    while (cursor !== '') {
      chain.push(cursor);
      cursor = this.blocks.get(cursor)?.parent ?? '';
    }
    chain.reverse();
    return chain;
  }

  private tip(): { id: string; height: number } {
    let id = '';
    let height = 0;
    for (const [digest, record] of this.blocks) {
      if (record.height > height || (record.height === height && digest < id)) {
        id = digest;
        height = record.height;
      }
    }
    return { id, height };
  }

  private parse(
    message: JsonValue,
  ): { digest: string; record: Stored } | undefined {
    const record = asRecord(message);
    if (record === undefined || record['consensus'] !== 'pow') return undefined;
    const height = record['height'];
    const nonce = record['nonce'];
    const miner = record['miner'];
    const parent = record['parent'];
    const payload = record['payload'];
    if (!isInt(height) || height < 1) return undefined;
    if (!isInt(nonce) || nonce < 0) return undefined;
    if (typeof miner !== 'string' || miner.length === 0) return undefined;
    if (typeof parent !== 'string') return undefined;
    if (typeof payload !== 'string' || payload.length === 0) return undefined;
    if (parent === '') {
      if (height !== 1) return undefined;
    } else {
      const prior = this.blocks.get(parent);
      if (prior === undefined || height !== prior.height + 1) return undefined;
    }
    const digest = blockId(height, miner, nonce, parent, payload);
    if (!meetsWork(digest, this.difficulty) || this.blocks.has(digest)) return undefined;
    return { digest, record: { height, miner, nonce, parent, payload } };
  }
}
