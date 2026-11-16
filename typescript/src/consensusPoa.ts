/** Proof-of-authority object — SPEC/features/consensus-poa.md. */

import type { JsonValue } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

export function proposerFor(height: number, authorities: readonly string[]): string {
  const index = (height - 1) % authorities.length;
  const proposer = authorities[index];
  if (proposer === undefined) {
    throw new RangeError('authorities must be non-empty');
  }
  return proposer;
}

export function blockId(
  height: number,
  parent: string,
  payload: string,
  proposer: string,
): string {
  return merkleDigest({ height, parent, payload, proposer });
}

interface Stored {
  height: number;
  parent: string;
  payload: string;
  proposer: string;
}

export class ProofOfAuthority extends BaseSharedObject {
  readonly authorities: readonly string[];
  private readonly blocks = new Map<string, Stored>();
  private readonly order: string[] = [];

  constructor(authorities: readonly string[]) {
    super();
    if (authorities.length === 0) {
      throw new RangeError('authorities must be non-empty');
    }
    const seen = new Set<string>();
    for (const authority of authorities) {
      if (typeof authority !== 'string' || authority.length === 0) {
        throw new RangeError('each authority must be a non-empty string');
      }
      if (seen.has(authority)) {
        throw new RangeError('authorities must be distinct');
      }
      seen.add(authority);
    }
    this.authorities = [...authorities];
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
    if (record === undefined || record['consensus'] !== 'poa') return undefined;
    const height = record['height'];
    const proposer = record['proposer'];
    const parent = record['parent'];
    const payload = record['payload'];
    if (!isInt(height) || height < 1) return undefined;
    if (typeof proposer !== 'string' || proposer.length === 0) return undefined;
    if (typeof parent !== 'string') return undefined;
    if (typeof payload !== 'string' || payload.length === 0) return undefined;
    if (proposer !== proposerFor(height, this.authorities)) return undefined;
    if (parent === '') {
      if (height !== 1) return undefined;
    } else {
      const prior = this.blocks.get(parent);
      if (prior === undefined || height !== prior.height + 1) return undefined;
    }
    const digest = blockId(height, parent, payload, proposer);
    if (this.blocks.has(digest)) return undefined;
    return { digest, record: { height, parent, payload, proposer } };
  }
}