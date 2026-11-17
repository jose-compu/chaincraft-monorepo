/** Proof-of-elapsed-time object — SPEC/features/consensus-poet.md. */

import type { JsonValue } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';
import { proofToHex, hexToProof, verify } from './vdf.ts';

function isWait(value: JsonValue | undefined): value is number {
  return (
    typeof value === 'number' &&
    Number.isSafeInteger(value) &&
    value >= 1 &&
    value <= 4_294_967_295
  );
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

function canonicalProofHex(text: JsonValue | undefined): string | undefined {
  if (typeof text !== 'string') return undefined;
  let proof: bigint;
  try {
    proof = hexToProof(text);
  } catch {
    return undefined;
  }
  const canonical = proofToHex(proof);
  if (canonical !== text) return undefined;
  return text;
}

export function ticketId(
  author: string,
  payload: string,
  proof: string,
  wait: number,
): string {
  return merkleDigest({ author, payload, proof, wait });
}

interface Stored {
  wait: number;
}

export class ProofOfElapsedTime extends BaseSharedObject {
  private readonly seedBytes: Uint8Array;
  private readonly tickets = new Map<string, Stored>();
  private readonly order: string[] = [];

  constructor(seed: string) {
    super();
    if (typeof seed !== 'string' || seed.length === 0) {
      throw new Error('seed must be a non-empty string');
    }
    this.seedBytes = new TextEncoder().encode(seed);
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
    this.tickets.set(parsed.digest, parsed.record);
    this.order.push(parsed.digest);
    return this.emitStateMemento();
  }

  override emitStateMemento(): StateMemento {
    const winner = this.winner();
    return StateMemento.normalize(
      merkleDigest({ v: 1, wait: winner.wait, winner: winner.id }),
      [],
    );
  }

  override getStateDigests(): string[] {
    const winner = this.winner();
    return winner.id ? [winner.id] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): { canonical: string[]; tickets: string[]; wait: number; winner: string } {
    const winner = this.winner();
    return {
      canonical: winner.id ? [winner.id] : [],
      tickets: [...this.order],
      wait: winner.wait,
      winner: winner.id,
    };
  }

  private winner(): { id: string; wait: number } {
    let id = '';
    let wait = 0;
    for (const [digest, record] of this.tickets) {
      if (
        record.wait < wait ||
        wait === 0 ||
        (record.wait === wait && (id === '' || digest < id))
      ) {
        id = digest;
        wait = record.wait;
      }
    }
    return { id, wait };
  }

  private parse(
    message: JsonValue,
  ): { digest: string; record: Stored } | undefined {
    const record = asRecord(message);
    if (record === undefined || record['consensus'] !== 'poet') return undefined;
    const wait = record['wait'];
    const author = record['author'];
    const payload = record['payload'];
    const proof = record['proof'];
    if (!isWait(wait)) return undefined;
    if (typeof author !== 'string' || author.length === 0) return undefined;
    if (typeof payload !== 'string' || payload.length === 0) return undefined;
    const proofHex = canonicalProofHex(proof);
    if (proofHex === undefined) return undefined;
    let proofInt: bigint;
    try {
      proofInt = hexToProof(proofHex);
    } catch {
      return undefined;
    }
    if (!verify(this.seedBytes, wait, proofInt)) return undefined;
    const digest = ticketId(author, payload, proofHex, wait);
    if (this.tickets.has(digest)) return undefined;
    return { digest, record: { wait } };
  }
}