/** UTXO ledger — SPEC/features/ledger-utxo.md. */

import { type JsonValue, compareCodePoints } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';

export const DEFAULT_ALLOCATIONS: Readonly<Record<string, number>> = { alice: 100 };

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

function normalizeAllocations(
  allocations: Readonly<Record<string, number>>,
): Record<string, number> {
  const ids = Object.keys(allocations).sort(compareCodePoints);
  if (ids.length === 0) throw new RangeError('allocations must not be empty');
  const out: Record<string, number> = {};
  for (const owner of ids) {
    const value = allocations[owner];
    if (!owner || value === undefined || !Number.isSafeInteger(value) || value < 1) {
      throw new RangeError('each allocation must be an integer in 1..2^53-1');
    }
    out[owner] = value;
  }
  return out;
}

export function transactionId(
  fee: number,
  inputs: readonly string[],
  outputs: readonly { owner: string; value: number }[],
): string {
  return merkleDigest({ fee, inputs: [...inputs], outputs: outputs.map((o) => ({ ...o })) });
}

export class UtxoLedger extends BaseSharedObject {
  private utxos: Record<string, { owner: string; value: number }>;
  private order: string[];
  private burned: number;

  constructor(allocations: Readonly<Record<string, number>> = DEFAULT_ALLOCATIONS) {
    super();
    const genesis = normalizeAllocations(allocations);
    this.utxos = {};
    this.order = [];
    for (const owner of Object.keys(genesis)) {
      const id = `genesis:${owner}`;
      this.utxos[id] = { owner, value: genesis[owner]! };
      this.order.push(id);
    }
    this.burned = 0;
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
    const { fee, inputs, outputs, txid } = parsed;
    for (const id of inputs) {
      delete this.utxos[id];
      this.order = this.order.filter((item) => item !== id);
    }
    for (const [index, output] of outputs.entries()) {
      const outId = `${txid}:${index}`;
      this.utxos[outId] = { owner: output.owner, value: output.value };
      this.order.push(outId);
    }
    this.burned += fee;
    return this.emitStateMemento();
  }

  override emitStateMemento(): StateMemento {
    return StateMemento.normalize(merkleDigest({ burned: this.burned, utxos: this.entries(), v: 1 }), []);
  }

  override getStateDigests(): string[] {
    const digest = this.emitStateMemento().canonicalDigest;
    return digest ? [digest] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): {
    burned: number;
    supply: number;
    utxos: { id: string; owner: string; value: number }[];
  } {
    const utxos = this.entries();
    let supply = 0;
    for (const item of utxos) supply += item.value;
    return { burned: this.burned, supply, utxos };
  }

  private entries(): { id: string; owner: string; value: number }[] {
    return this.order.map((id) => ({
      id,
      owner: this.utxos[id]!.owner,
      value: this.utxos[id]!.value,
    }));
  }

  private parse(message: JsonValue):
    | {
        fee: number;
        inputs: string[];
        outputs: { owner: string; value: number }[];
        txid: string;
      }
    | undefined {
    const record = asRecord(message);
    if (record === undefined || record['ledger'] !== 'utxo') return undefined;
    const fee = record['fee'];
    const rawInputs = record['inputs'];
    const rawOutputs = record['outputs'];
    if (!isInt(fee) || fee < 0) return undefined;
    if (!Array.isArray(rawInputs) || rawInputs.length === 0) return undefined;
    const inputs: string[] = [];
    const seen = new Set<string>();
    let incoming = 0;
    for (const item of rawInputs) {
      if (typeof item !== 'string' || item.length === 0 || seen.has(item)) return undefined;
      const stored = this.utxos[item];
      if (stored === undefined) return undefined;
      seen.add(item);
      inputs.push(item);
      incoming += stored.value;
    }
    if (!Array.isArray(rawOutputs)) return undefined;
    const outputs: { owner: string; value: number }[] = [];
    let outgoing = 0;
    for (const item of rawOutputs) {
      const output = asRecord(item);
      if (output === undefined) return undefined;
      const owner = output['owner'];
      const value = output['value'];
      if (typeof owner !== 'string' || owner.length === 0) return undefined;
      if (!isInt(value) || value < 1) return undefined;
      outgoing += value;
      outputs.push({ owner, value });
    }
    if (incoming !== outgoing + fee) return undefined;
    return { fee, inputs, outputs, txid: transactionId(fee, inputs, outputs) };
  }
}
