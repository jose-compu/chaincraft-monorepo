/** Slush, Snowflake, and Snowball — SPEC/features/consensus-avalanche.md. */

import type { JsonValue } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';

export const PHASES = ['slush', 'snowflake', 'snowball'] as const;
export const COLORS = ['blue', 'red'] as const;
export const DEFAULT_K = 2;
export const DEFAULT_ALPHA = 2;
export const DEFAULT_BETA = 2;

type Phase = (typeof PHASES)[number];
type Color = (typeof COLORS)[number];

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

function isPhase(value: string): value is Phase {
  return PHASES.includes(value as Phase);
}

function isColor(value: string): value is Color {
  return COLORS.includes(value as Color);
}

export class Avalanche extends BaseSharedObject {
  readonly phase: Phase;
  readonly k: number;
  readonly alpha: number;
  readonly beta: number;
  pref = '';
  finalized = false;
  cnt = 0;
  rounds = 0;
  private dBlue = 0;
  private dRed = 0;

  constructor(
    phase: string = 'snowball',
    k: number = DEFAULT_K,
    alpha: number = DEFAULT_ALPHA,
    beta: number = DEFAULT_BETA,
  ) {
    super();
    if (!isPhase(phase)) {
      throw new RangeError('phase must be slush, snowflake, or snowball');
    }
    if (!Number.isSafeInteger(k) || k < 1 || k > 16) {
      throw new RangeError('k must be in 1..16');
    }
    if (!Number.isSafeInteger(alpha) || alpha < 1 || alpha > k || alpha * 2 <= k) {
      throw new RangeError('alpha must be in 1..k and greater than k/2');
    }
    if (!Number.isSafeInteger(beta) || beta < 1 || beta > 16) {
      throw new RangeError('beta must be in 1..16');
    }
    this.phase = phase;
    this.k = k;
    this.alpha = alpha;
    this.beta = beta;
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
    if (parsed.kind === 'init') {
      this.pref = parsed.color;
    } else {
      this.applyRound(parsed.winner);
    }
    return this.emitStateMemento();
  }

  override emitStateMemento(): StateMemento {
    return StateMemento.normalize(merkleDigest({ state: this.state(), v: 1 }), []);
  }

  override getStateDigests(): string[] {
    const head = this.emitStateMemento().canonicalDigest;
    return head ? [head] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): {
    cnt: number;
    d: { blue: number; red: number };
    final: boolean;
    phase: Phase;
    pref: string;
    rounds: number;
  } {
    return {
      cnt: this.cnt,
      d: { blue: this.dBlue, red: this.dRed },
      final: this.finalized,
      phase: this.phase,
      pref: this.pref,
      rounds: this.rounds,
    };
  }

  private confidence(color: string): number {
    if (color === 'blue') return this.dBlue;
    if (color === 'red') return this.dRed;
    return 0;
  }

  private applyRound(winner: Color | undefined): void {
    this.rounds += 1;
    if (winner === undefined) {
      if (this.phase === 'snowflake') this.cnt = 0;
      return;
    }
    if (this.phase === 'slush') {
      this.pref = winner;
      return;
    }
    if (this.phase === 'snowflake') {
      if (this.pref === '' || this.pref === winner) {
        this.pref = winner;
        this.cnt += 1;
      } else {
        this.pref = winner;
        this.cnt = 1;
      }
      if (this.cnt >= this.beta) this.finalized = true;
      return;
    }
    if (winner === 'blue') this.dBlue += 1;
    else this.dRed += 1;
    const dColor = this.confidence(winner);
    const dPref = this.confidence(this.pref);
    if (this.pref === '' || dColor > dPref || (dColor === dPref && winner < this.pref)) {
      this.pref = winner;
    }
    if (this.confidence(this.pref) >= this.beta) this.finalized = true;
  }

  private parse(
    message: JsonValue,
  ): { kind: 'init'; color: Color } | { kind: 'round'; winner: Color | undefined } | undefined {
    const record = asRecord(message);
    if (record === undefined || record['consensus'] !== 'avalanche') return undefined;
    const op = record['op'];
    if (op === 'init') {
      const color = record['color'];
      if (typeof color !== 'string' || !isColor(color) || this.pref) return undefined;
      return { kind: 'init', color };
    }
    if (op !== 'round' || this.finalized) return undefined;
    const votes = record['votes'];
    if (!Array.isArray(votes) || votes.length !== this.k) return undefined;
    let blue = 0;
    let red = 0;
    for (const vote of votes) {
      if (vote !== 'blue' && vote !== 'red') return undefined;
      if (vote === 'blue') blue += 1;
      else red += 1;
    }
    let winner: Color | undefined;
    if (blue >= this.alpha) winner = 'blue';
    if (red >= this.alpha) winner = 'red';
    return { kind: 'round', winner };
  }
}
