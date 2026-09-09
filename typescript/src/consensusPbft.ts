/** PBFT object — SPEC/features/consensus-pbft.md. */

import type { JsonValue } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';

export const DEFAULT_REPLICAS = ['r0', 'r1', 'r2', 'r3'] as const;
export const PHASES = ['pre-prepare', 'prepare', 'commit'] as const;

const HEX64 = /^[0-9a-f]{64}$/;

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

export class PBFT extends BaseSharedObject {
  readonly replicas: readonly string[];
  readonly n: number;
  readonly f: number;
  readonly quorum: number;
  view = 0;
  sequence = 1;
  private digest = '';
  private readonly prepares = new Map<string, string>();
  private readonly commits = new Map<string, string>();
  executed: Array<{ digest: string; seq: number }> = [];

  constructor(replicas: readonly string[] = DEFAULT_REPLICAS) {
    super();
    if (replicas.length === 0 || new Set(replicas).size !== replicas.length) {
      throw new RangeError('replicas must be unique non-empty ids');
    }
    if (replicas.some((name) => !name)) {
      throw new RangeError('replicas must be unique non-empty ids');
    }
    this.replicas = [...replicas].sort();
    this.n = this.replicas.length;
    this.f = Math.floor((this.n - 1) / 3);
    this.quorum = 2 * this.f + 1;
  }

  primaryFor(view: number): string {
    return this.replicas[view % this.n] ?? '';
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
    if (parsed.view !== this.view || parsed.sequence !== this.sequence) {
      return this.emitStateMemento();
    }
    if (parsed.phase === 'pre-prepare') {
      if (!this.digest) this.digest = parsed.digest;
    } else if (!this.digest || parsed.digest !== this.digest) {
      return this.emitStateMemento();
    } else if (parsed.phase === 'prepare') {
      if (!this.prepares.has(parsed.replica)) {
        this.prepares.set(parsed.replica, parsed.digest);
      }
    } else if (!this.commits.has(parsed.replica)) {
      this.commits.set(parsed.replica, parsed.digest);
    }
    if (
      this.digest &&
      this.count(this.prepares) >= this.quorum &&
      this.count(this.commits) >= this.quorum
    ) {
      this.executed.push({ digest: this.digest, seq: this.sequence });
      this.sequence += 1;
      this.digest = '';
      this.prepares.clear();
      this.commits.clear();
    }
    return this.emitStateMemento();
  }

  override emitStateMemento(): StateMemento {
    return StateMemento.normalize(
      merkleDigest({
        executed: this.executed.map((item) => item.digest),
        sequence: this.sequence,
        v: 1,
      }),
      [],
    );
  }

  override getStateDigests(): string[] {
    const head = this.emitStateMemento().canonicalDigest;
    return head ? [head] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): {
    commits: number;
    executed: Array<{ digest: string; seq: number }>;
    prepares: number;
    sequence: number;
    view: number;
  } {
    return {
      commits: this.count(this.commits),
      executed: this.executed.map((item) => ({ ...item })),
      prepares: this.count(this.prepares),
      sequence: this.sequence,
      view: this.view,
    };
  }

  private count(votes: Map<string, string>): number {
    let n = 0;
    for (const digest of votes.values()) {
      if (digest === this.digest) n += 1;
    }
    return n;
  }

  private parse(message: JsonValue):
    | {
        phase: (typeof PHASES)[number];
        view: number;
        sequence: number;
        digest: string;
        replica: string;
      }
    | undefined {
    const record = asRecord(message);
    if (record === undefined || record['consensus'] !== 'pbft') return undefined;
    const phase = record['phase'];
    const view = record['view'];
    const sequence = record['sequence'];
    const digest = record['digest'];
    const replica = record['replica'];
    if (phase !== 'pre-prepare' && phase !== 'prepare' && phase !== 'commit') {
      return undefined;
    }
    if (!isInt(view) || view < 0) return undefined;
    if (!isInt(sequence) || sequence < 1) return undefined;
    if (typeof digest !== 'string' || !HEX64.test(digest)) return undefined;
    if (typeof replica !== 'string' || !this.replicas.includes(replica)) return undefined;
    if (phase === 'pre-prepare') {
      const value = record['value'];
      if (typeof value !== 'string') return undefined;
      if (digest !== merkleDigest(value)) return undefined;
      if (replica !== this.primaryFor(view)) return undefined;
    }
    return { phase, view, sequence, digest, replica };
  }
}
