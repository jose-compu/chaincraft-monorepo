/**
 * Shared object contract and digest helpers — SPEC/semantics-v1.md §2, §5, §6.
 */

import { sha256 } from '@noble/hashes/sha2.js';
import {
  type JsonValue,
  bytesToHex,
  canonicalBytes,
  compareCodePoints,
} from './canonical.ts';
import { StateMemento } from './memento.ts';

export const FRONTIER_FORMAT_VERSION = 1;

/**
 * Merkelized object digest — §5.
 *
 * Deliberately the same canonicalization as the wire payload digest. Using a
 * second canonicalization for state hashing is the mistake this shares code to
 * avoid.
 */
export function merkleDigest(statePayload: JsonValue): string {
  return bytesToHex(sha256(canonicalBytes(statePayload)));
}

/** Digest over a multi-head frontier — §5.1. */
export function frontierDigest(heads: readonly string[]): string {
  const payload = {
    frontier_heads: heads.filter((head) => head).sort(compareCodePoints),
    v: FRONTIER_FORMAT_VERSION,
  };
  return bytesToHex(sha256(canonicalBytes(payload)));
}

/**
 * Whether a candidate entry replaces the incumbent — §6.1.
 *
 * An identical entry does not replace itself. Gossip redelivers the same
 * message by design, so returning true on an exact match would let repeated
 * delivery mutate state.
 */
export function winsReplacement(
  candidateRank: number,
  candidateDigest: string,
  incumbentRank: number,
  incumbentDigest: string,
): boolean {
  if (candidateRank > incumbentRank) return true;
  if (candidateRank < incumbentRank) return false;
  return candidateDigest < incumbentDigest;
}

/**
 * The application object contract — §2.
 *
 * Called `SharedObject` here and in Python, `ApplicationObject` in Rust. The
 * names differ; the contract does not.
 */
export interface SharedObject {
  /**
   * Whether `message` is an acceptable transition.
   *
   * MUST be deterministic and side-effect free. The pipeline calls this on every
   * object before any object mutates, so a mutation here breaks the
   * all-or-nothing guarantee in §3.
   */
  /** Side-effect free. The default accepts. */
  isValid(message: JsonValue): boolean;

  /** Local apply. A prototype overrides this and nothing else. */
  receive(message: JsonValue): void;

  /** Defaults to `receive` and returns nothing. Override to sync. */
  addMessage(
    message: JsonValue,
    frontierState?: StateMemento | undefined,
  ): StateMemento | undefined;

  /** Snapshot of current state. */
  emitStateMemento(): StateMemento;

  /** Frontier digests for multi-head structures. */
  getStateDigests(): string[];

  /** Whether canonical digests are meaningful for this object. */
  isMerkelized(): boolean;
}

/** Defaults: accept, apply locally, empty snapshot. Consensus objects override. */
export class BaseSharedObject implements SharedObject {
  isValid(_message: JsonValue): boolean {
    return true;
  }

  receive(_message: JsonValue): void {}

  addMessage(
    message: JsonValue,
    _frontierState?: StateMemento | undefined,
  ): StateMemento | undefined {
    this.receive(message);
    return undefined;
  }

  emitStateMemento(): StateMemento {
    return StateMemento.normalize();
  }

  getStateDigests(): string[] {
    return [];
  }

  isMerkelized(): boolean {
    return false;
  }
}
