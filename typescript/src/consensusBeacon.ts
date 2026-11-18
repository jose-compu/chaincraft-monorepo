/** Chained VRF randomness beacon — SPEC/features/consensus-beacon.md. */

import type { JsonValue } from './canonical.ts';
import { MAX_SAFE_INT, canonicalJson } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';
import { hexToBytes } from './canonical.ts';
import { verify } from './vrf.ts';

export const GENESIS_PREVIOUS =
  '0000000000000000000000000000000000000000000000000000000000000000';

function isHeight(value: JsonValue | undefined): value is number {
  return (
    typeof value === 'number' &&
    Number.isSafeInteger(value) &&
    value >= 0 &&
    value <= MAX_SAFE_INT
  );
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
    const bytes = hexToBytes(text);
    if (bytes.length !== nbytes) return undefined;
  } catch {
    return undefined;
  }
  return text;
}

export function pulseId(
  height: number,
  output: string,
  pk: string,
  previous: string,
  proof: string,
): string {
  return merkleDigest({ height, output, pk, previous, proof });
}

interface Stored {
  height: number;
  output: string;
}

export class RandomnessBeacon extends BaseSharedObject {
  private readonly pulses = new Map<string, Stored>();
  private readonly order: string[] = [];

  override isValid(message: JsonValue): boolean {
    return this.parse(message) !== undefined;
  }

  override addMessage(
    message: JsonValue,
    _frontierState?: StateMemento | undefined,
  ): StateMemento | undefined {
    const parsed = this.parse(message);
    if (parsed === undefined) return this.emitStateMemento();
    this.pulses.set(parsed.digest, parsed.record);
    this.order.push(parsed.digest);
    return this.emitStateMemento();
  }

  override emitStateMemento(): StateMemento {
    const tip = this.tip();
    return StateMemento.normalize(
      merkleDigest({ height: tip.height, output: tip.output, v: 1 }),
      [],
    );
  }

  override getStateDigests(): string[] {
    const last = this.order[this.order.length - 1];
    return last !== undefined ? [last] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): { canonical: string[]; height: number; output: string; pulses: string[] } {
    const pulses = [...this.order];
    const tip = this.tip();
    return {
      canonical: pulses,
      height: tip.height,
      output: tip.output,
      pulses,
    };
  }

  private tip(): { height: number; output: string } {
    const last = this.order[this.order.length - 1];
    if (last === undefined) {
      return { height: -1, output: '' };
    }
    const record = this.pulses.get(last);
    if (record === undefined) {
      return { height: -1, output: '' };
    }
    return { height: record.height, output: record.output };
  }

  private parse(
    message: JsonValue,
  ): { digest: string; record: Stored } | undefined {
    const record = asRecord(message);
    if (record === undefined || record['consensus'] !== 'beacon') return undefined;
    const height = record['height'];
    const previous = hexLower(record['previous'], 32);
    const pk = hexLower(record['pk'], 33);
    const proof = hexLower(record['proof'], 64);
    const outputHex = hexLower(record['output'], 32);
    if (!isHeight(height)) return undefined;
    if (
      previous === undefined ||
      pk === undefined ||
      proof === undefined ||
      outputHex === undefined
    ) {
      return undefined;
    }
    const tip = this.tip();
    if (tip.height < 0) {
      if (height !== 0 || previous !== GENESIS_PREVIOUS) return undefined;
    } else if (height !== tip.height + 1 || previous !== tip.output) {
      return undefined;
    }
    const vrfMessage = new TextEncoder().encode(
      canonicalJson({ height, previous }),
    );
    if (
      !verify(
        vrfMessage,
        hexToBytes(proof),
        hexToBytes(pk),
        hexToBytes(outputHex),
      )
    ) {
      return undefined;
    }
    const digest = pulseId(height, outputHex, pk, previous, proof);
    if (this.pulses.has(digest)) return undefined;
    return { digest, record: { height, output: outputHex } };
  }
}