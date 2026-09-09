/** Account-balance ledger — SPEC/features/ledger-balance.md. */

import { type JsonValue, MAX_SAFE_INT, compareCodePoints } from './canonical.ts';
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
  for (const account of ids) {
    const amount = allocations[account];
    if (!account || amount === undefined || !Number.isSafeInteger(amount) || amount < 1) {
      throw new RangeError('each allocation must be an integer in 1..2^53-1');
    }
    out[account] = amount;
  }
  return out;
}

export class BalanceLedger extends BaseSharedObject {
  private balances: Record<string, number>;
  private nonces: Record<string, number>;
  private burned: number;

  constructor(allocations: Readonly<Record<string, number>> = DEFAULT_ALLOCATIONS) {
    super();
    this.balances = normalizeAllocations(allocations);
    this.nonces = {};
    for (const account of Object.keys(this.balances)) this.nonces[account] = 0;
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
    const { sender, recipient, amount, fee } = parsed;
    this.balances[sender] = (this.balances[sender] ?? 0) - amount - fee;
    this.balances[recipient] = (this.balances[recipient] ?? 0) + amount;
    if (this.nonces[recipient] === undefined) this.nonces[recipient] = 0;
    this.nonces[sender] = (this.nonces[sender] ?? 0) + 1;
    this.burned += fee;
    return this.emitStateMemento();
  }

  override emitStateMemento(): StateMemento {
    return StateMemento.normalize(
      merkleDigest({
        balances: this.balances,
        burned: this.burned,
        nonces: this.nonces,
        v: 1,
      }),
      [],
    );
  }

  override getStateDigests(): string[] {
    const digest = this.emitStateMemento().canonicalDigest;
    return digest ? [digest] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): {
    balances: Record<string, number>;
    burned: number;
    nonces: Record<string, number>;
    supply: number;
  } {
    let supply = 0;
    for (const value of Object.values(this.balances)) supply += value;
    return {
      balances: { ...this.balances },
      burned: this.burned,
      nonces: { ...this.nonces },
      supply,
    };
  }

  private parse(
    message: JsonValue,
  ): { sender: string; recipient: string; amount: number; fee: number } | undefined {
    const record = asRecord(message);
    if (record === undefined || record['ledger'] !== 'balance') return undefined;
    const sender = record['sender'];
    const recipient = record['recipient'];
    const amount = record['amount'];
    const fee = record['fee'];
    const nonce = record['nonce'];
    if (typeof sender !== 'string' || sender.length === 0) return undefined;
    if (typeof recipient !== 'string' || recipient.length === 0) return undefined;
    if (!isInt(amount) || amount < 1) return undefined;
    if (!isInt(fee) || fee < 0) return undefined;
    if (!isInt(nonce) || nonce < 0) return undefined;
    if (nonce !== (this.nonces[sender] ?? 0)) return undefined;
    if ((this.balances[sender] ?? 0) < amount + fee) return undefined;
    if ((this.balances[recipient] ?? 0) + amount > MAX_SAFE_INT) return undefined;
    return { sender, recipient, amount, fee };
  }
}
