/** StateMemento — SPEC/semantics-v1.md §4. */

import { type JsonValue, compareCodePoints } from './canonical.ts';

/**
 * Serialized form. Keys are snake_case because this is the shared cross-language
 * format the conformance vectors pin; the class properties stay camelCase
 * because that is the local idiom. Parity is of bytes, not of naming.
 */
export interface StateMementoObject {
  readonly canonical_digest: string;
  readonly frontier_digests: string[];
  readonly revision: number;
  readonly metadata: Record<string, JsonValue>;
}

export class StateMemento {
  readonly canonicalDigest: string;
  readonly frontierDigests: readonly string[];
  readonly revision: number;
  readonly metadata: Readonly<Record<string, JsonValue>>;

  constructor(
    canonicalDigest = '',
    frontierDigests: readonly string[] = [],
    revision = 0,
    metadata: Readonly<Record<string, JsonValue>> = {},
  ) {
    this.canonicalDigest = canonicalDigest;
    this.frontierDigests = frontierDigests;
    this.revision = revision;
    this.metadata = metadata;
  }

  /**
   * Build a normalized memento — §4.1.
   *
   * The frontier is sorted and deduplicated so two nodes reaching the same set
   * of heads by different routes produce the same memento.
   */
  static normalize(
    canonicalDigest = '',
    frontierDigests: readonly string[] = [],
  ): StateMemento {
    const collected = new Set<string>();
    for (const head of frontierDigests) {
      if (head) collected.add(head);
    }
    if (canonicalDigest) collected.add(canonicalDigest);
    return new StateMemento(
      canonicalDigest,
      Array.from(collected).sort(compareCodePoints),
      0,
      {},
    );
  }

  /**
   * Whether the head moved to a branch that does not build on `previous` — §4.2.
   * All four conditions must hold.
   */
  indicatesReorgAgainst(previous: StateMemento | undefined | null): boolean {
    if (previous === undefined || previous === null) return false;
    if (!this.canonicalDigest || !previous.canonicalDigest) return false;
    if (this.canonicalDigest === previous.canonicalDigest) return false;
    return !this.frontierDigests.includes(previous.canonicalDigest);
  }

  toObject(): StateMementoObject {
    return {
      canonical_digest: this.canonicalDigest,
      frontier_digests: [...this.frontierDigests],
      revision: this.revision,
      metadata: { ...this.metadata },
    };
  }

  equals(other: StateMemento): boolean {
    return (
      this.canonicalDigest === other.canonicalDigest &&
      this.revision === other.revision &&
      this.frontierDigests.length === other.frontierDigests.length &&
      this.frontierDigests.every((d, i) => d === other.frontierDigests[i])
    );
  }
}
