/** Ouroboros slot-leader object — SPEC/features/consensus-ouroboros.md. */

import type { JsonValue } from './canonical.ts';
import { canonicalJson } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';
import * as vrf from './vrf.ts';

const MAX_INT = 9007199254740991;
const NONCE_RE = /^[0-9a-f]{64}$/;
const THRESHOLD = 1n << 256n;

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= MAX_INT;
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

function hexLower(text: JsonValue | undefined, nbytes: number): string | undefined {
  if (typeof text !== 'string' || text.length !== nbytes * 2) return undefined;
  if (text !== text.toLowerCase()) return undefined;
  try {
    Buffer.from(text, 'hex');
  } catch {
    return undefined;
  }
  return text;
}

export function epochOf(slot: number, epochLength: number): number {
  return Math.floor((slot - 1) / epochLength);
}

export function eligible(output: Uint8Array, stake: number, total: number): boolean {
  if (total === stake) return true;
  let oVal = 0n;
  for (const byte of output) {
    oVal = (oVal << 8n) + BigInt(byte);
  }
  return oVal * BigInt(total) < BigInt(stake) * THRESHOLD;
}

export function blockId(
  slot: number,
  parent: string,
  payload: string,
  leader: string,
  pk: string,
  proof: string,
  output: string,
): string {
  return merkleDigest({ leader, output, parent, payload, pk, proof, slot });
}

interface Stored {
  slot: number;
  parent: string;
  output: string;
  epoch_nonce: string;
}

interface Stakeholder {
  stake: number;
  pk: string;
}

export class Ouroboros extends BaseSharedObject {
  readonly nonce: string;
  readonly epochLength: number;
  private readonly stakeholders = new Map<string, Stakeholder>();
  private readonly totalStake: number;
  private readonly blocks = new Map<string, Stored>();
  private readonly order: string[] = [];

  constructor(
    nonce: string,
    epochLength: number,
    stakeholders: readonly { id: string; stake: number; pk: string }[],
  ) {
    super();
    if (!NONCE_RE.test(nonce)) {
      throw new RangeError('nonce must be 64 lowercase hex characters');
    }
    if (!isInt(epochLength) || epochLength < 1) {
      throw new RangeError('epoch_length must be an integer >= 1');
    }
    if (stakeholders.length === 0) {
      throw new RangeError('stakeholders must be non-empty');
    }
    const seen = new Set<string>();
    let total = 0;
    for (const entry of stakeholders) {
      if (typeof entry.id !== 'string' || entry.id.length === 0) {
        throw new RangeError('each stakeholder id must be a non-empty string');
      }
      if (!isInt(entry.stake) || entry.stake < 1) {
        throw new RangeError('each stake must be an integer >= 1');
      }
      if (hexLower(entry.pk, 33) === undefined) {
        throw new RangeError('each pk must be 66 lowercase hex characters');
      }
      if (seen.has(entry.id)) {
        throw new RangeError('stakeholder ids must be distinct');
      }
      seen.add(entry.id);
      total += entry.stake;
      if (total > MAX_INT) {
        throw new RangeError('stake sum exceeds safe integer range');
      }
      this.stakeholders.set(entry.id, { stake: entry.stake, pk: entry.pk });
    }
    this.nonce = nonce;
    this.epochLength = epochLength;
    this.totalStake = total;
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
    const ctx = this.nextSlotContext(tip.slot, tip.id);
    return StateMemento.normalize(
      merkleDigest({ nonce: ctx.nonce, slot: tip.slot, tip: tip.id, v: 1 }),
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

  state(): {
    slot: number;
    tip: string;
    canonical: string[];
    blocks: string[];
    epoch: number;
    nonce: string;
  } {
    const tip = this.tip();
    const ctx = this.nextSlotContext(tip.slot, tip.id);
    return {
      slot: tip.slot,
      tip: tip.id,
      canonical: this.canonical(tip.id),
      blocks: [...this.order],
      epoch: ctx.epoch,
      nonce: ctx.nonce,
    };
  }

  private tip(): { id: string; slot: number } {
    let id = '';
    let slot = 0;
    for (const [digest, record] of this.blocks) {
      if (record.slot > slot || (record.slot === slot && digest < id)) {
        id = digest;
        slot = record.slot;
      }
    }
    return { id, slot };
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

  private nextSlotContext(tipSlot: number, tip: string): { epoch: number; nonce: string } {
    if (tipSlot === 0) {
      return { epoch: epochOf(1, this.epochLength), nonce: this.nonce };
    }
    return this.epochNonceForSlot(tipSlot + 1, this.blocks.get(tip));
  }

  private epochNonceForSlot(slot: number, parent: Stored | undefined): { epoch: number; nonce: string } {
    const epoch = epochOf(slot, this.epochLength);
    const pos = (slot - 1) % this.epochLength;
    if (epoch === 0) {
      return { epoch, nonce: this.nonce };
    }
    if (pos === 0) {
      if (parent === undefined) throw new RangeError('parent required');
      return { epoch, nonce: parent.output };
    }
    if (parent === undefined) throw new RangeError('parent required');
    return { epoch, nonce: parent.epoch_nonce };
  }

  private vrfMessage(epoch: number, nonce: string, slot: number, leader: string): Uint8Array {
    return new TextEncoder().encode(
      canonicalJson({ epoch, nonce, slot, stakeholder: leader }),
    );
  }

  private parse(message: JsonValue): { digest: string; record: Stored } | undefined {
    const obj = asRecord(message);
    if (obj === undefined || obj['consensus'] !== 'ouroboros') return undefined;
    const slot = obj['slot'];
    const leader = obj['leader'];
    const parent = obj['parent'];
    const payload = obj['payload'];
    const pk = hexLower(obj['pk'], 33);
    const proof = hexLower(obj['proof'], 64);
    const outputHex = hexLower(obj['output'], 32);
    if (!isInt(slot) || slot < 1) return undefined;
    if (typeof leader !== 'string' || leader.length === 0) return undefined;
    if (typeof parent !== 'string') return undefined;
    if (typeof payload !== 'string' || payload.length === 0) return undefined;
    if (pk === undefined || proof === undefined || outputHex === undefined) return undefined;
    const holder = this.stakeholders.get(leader);
    if (holder === undefined || holder.pk !== pk) return undefined;
    let parentRecord: Stored | undefined;
    if (parent === '') {
      if (slot !== 1) return undefined;
    } else {
      parentRecord = this.blocks.get(parent);
      if (parentRecord === undefined || parentRecord.slot !== slot - 1) return undefined;
    }
    const ctx = this.epochNonceForSlot(slot, parentRecord);
    const vrfMsg = this.vrfMessage(ctx.epoch, ctx.nonce, slot, leader);
    const proofBytes = Buffer.from(proof, 'hex');
    const pkBytes = Buffer.from(pk, 'hex');
    const outputBytes = Buffer.from(outputHex, 'hex');
    if (!vrf.verify(vrfMsg, proofBytes, pkBytes, outputBytes)) return undefined;
    if (!eligible(outputBytes, holder.stake, this.totalStake)) return undefined;
    const digest = blockId(slot, parent, payload, leader, pk, proof, outputHex);
    if (this.blocks.has(digest)) return undefined;
    const pos = (slot - 1) % this.epochLength;
    let epochNonce: string;
    if (ctx.epoch === 0) {
      epochNonce = this.nonce;
    } else if (pos === 0) {
      epochNonce = parentRecord!.output;
    } else {
      epochNonce = parentRecord!.epoch_nonce;
    }
    return {
      digest,
      record: {
        slot,
        parent,
        output: outputHex,
        epoch_nonce: epochNonce,
      },
    };
  }
}