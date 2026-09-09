/** Proof-of-stake object — SPEC/features/consensus-pos.md. */

import type { JsonValue } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';

export const DEFAULT_SEED = 'chaincraft-pos-v1';
export const DEFAULT_VALIDATORS: Readonly<Record<string, number>> = {
  alice: 2,
  bob: 1,
  carol: 1,
};

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

export function proposerFor(
  slot: number,
  seed: string,
  validators: Readonly<Record<string, number>>,
): string {
  const ids = Object.keys(validators).sort();
  let total = 0;
  for (const id of ids) total += validators[id] ?? 0;
  const digest = merkleDigest({ seed, slot });
  let pick = 0n;
  for (const ch of digest) pick = (pick << 4n) + BigInt(parseInt(ch, 16));
  pick %= BigInt(total);
  let acc = 0n;
  for (const id of ids) {
    acc += BigInt(validators[id] ?? 0);
    if (pick < acc) return id;
  }
  throw new Error('stake walk missed');
}

export class ProofOfStake extends BaseSharedObject {
  readonly seed: string;
  readonly validators: Readonly<Record<string, number>>;
  current = 0;
  lastProposer = '';
  head = '';

  constructor(
    seed: string = DEFAULT_SEED,
    validators: Readonly<Record<string, number>> = DEFAULT_VALIDATORS,
  ) {
    super();
    if (!seed) throw new RangeError('seed must be a non-empty string');
    const ids = Object.keys(validators);
    if (ids.length === 0) throw new RangeError('validators must not be empty');
    for (const id of ids) {
      const stake = validators[id];
      if (!id || stake === undefined || !Number.isSafeInteger(stake) || stake < 1) {
        throw new RangeError('each validator needs a non-empty id and positive stake');
      }
    }
    this.seed = seed;
    this.validators = { ...validators };
  }

  proposer(slot: number): string {
    return proposerFor(slot, this.seed, this.validators);
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
    this.current = parsed.slot;
    this.lastProposer = parsed.proposer;
    this.head = merkleDigest({ payload: parsed.payload, slot: parsed.slot, v: 1 });
    return this.emitStateMemento();
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

  state(): { head: string; last_proposer: string; slot: number } {
    return { head: this.head, last_proposer: this.lastProposer, slot: this.current };
  }

  private parse(
    message: JsonValue,
  ): { slot: number; proposer: string; payload: string } | undefined {
    const record = asRecord(message);
    if (record === undefined || record['consensus'] !== 'pos') return undefined;
    const slot = record['slot'];
    const proposer = record['proposer'];
    const payload = record['payload'];
    if (!isInt(slot) || slot !== this.current + 1) return undefined;
    if (typeof proposer !== 'string' || proposer.length === 0) return undefined;
    if (typeof payload !== 'string' || payload.length === 0) return undefined;
    if (proposer !== this.proposer(slot)) return undefined;
    return { slot, proposer, payload };
  }
}
