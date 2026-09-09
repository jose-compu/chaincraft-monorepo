/** Deduplication and relay — SPEC/wire-v1.md §7. */

import type { Envelope } from './envelope.ts';

export const DEFAULT_CAPACITY = 100000;

/**
 * Bounded set of seen payload digests, evicting the oldest insertion first.
 *
 * A `Set` is already insertion-ordered and leaves that order undisturbed when a
 * value is re-added, which is exactly the no-refresh rule in §7.2.
 */
export class SeenDigests {
  private readonly digests = new Set<string>();
  readonly capacity: number;

  constructor(capacity: number = DEFAULT_CAPACITY) {
    if (!Number.isSafeInteger(capacity) || capacity < 1) {
      throw new RangeError('capacity must be a positive integer');
    }
    this.capacity = capacity;
  }

  has(digest: string): boolean {
    return this.digests.has(digest);
  }

  /** Record a digest. Returns false when it was already present. */
  add(digest: string): boolean {
    if (this.digests.has(digest)) return false;
    if (this.digests.size >= this.capacity) {
      const oldest = this.digests.values().next();
      if (!oldest.done) this.digests.delete(oldest.value);
    }
    this.digests.add(digest);
    return true;
  }

  get size(): number {
    return this.digests.size;
  }

  clear(): void {
    this.digests.clear();
  }
}

/**
 * The receive-path gate.
 *
 * `shouldProcess` has the side effect of recording the digest, so a caller must
 * ask once per received envelope and act on the answer. `shouldRelay` assumes
 * the caller only relays what `shouldProcess` accepted.
 */
export class Deduplicator {
  readonly seen: SeenDigests;

  constructor(capacity: number = DEFAULT_CAPACITY) {
    this.seen = new SeenDigests(capacity);
  }

  shouldProcess(envelope: Envelope): boolean {
    // Control messages are point-to-point, so the same ctl.hello arriving on
    // two connections must be handled twice, not silently dropped as a repeat.
    if (envelope.isControl()) return true;
    return this.seen.add(envelope.id);
  }

  shouldRelay(envelope: Envelope): boolean {
    return !envelope.isControl();
  }
}
