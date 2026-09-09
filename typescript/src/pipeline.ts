/** The apply pipeline — SPEC/semantics-v1.md §3. */

import type { JsonValue } from './canonical.ts';
import type { StateMemento } from './memento.ts';
import type { SharedObject } from './object.ts';

export interface ApplyResult {
  readonly accepted: boolean;
  readonly rejectedBy: string | undefined;
  readonly mementos: ReadonlyMap<string, StateMemento>;
  /** §3 step 5 — persist and broadcast only on full success. */
  readonly shouldPersist: boolean;
}

/**
 * Objects in registration order, with the validate-all-then-apply pipeline.
 *
 * Registration order is load-bearing: it fixes the order in which mementos are
 * threaded, so two nodes registering the same objects in different orders will
 * compute different state.
 */
export class ObjectRegistry {
  private readonly entries: Array<{ name: string; object: SharedObject }> = [];

  register(name: string, object: SharedObject): this {
    if (this.entries.some((entry) => entry.name === name)) {
      throw new Error(`object already registered: ${name}`);
    }
    this.entries.push({ name, object });
    return this;
  }

  get names(): string[] {
    return this.entries.map((entry) => entry.name);
  }

  get(name: string): SharedObject {
    const entry = this.entries.find((candidate) => candidate.name === name);
    if (entry === undefined) {
      throw new Error(`no such object: ${name}`);
    }
    return entry.object;
  }

  /**
   * Validate against every object, then apply to each in order.
   *
   * Nothing mutates unless every object accepts, so a rejected message leaves
   * the registry exactly as it was before the call.
   */
  apply(message: JsonValue): ApplyResult {
    for (const entry of this.entries) {
      if (!entry.object.isValid(message)) {
        return {
          accepted: false,
          rejectedBy: entry.name,
          mementos: new Map(),
          shouldPersist: false,
        };
      }
    }

    const mementos = new Map<string, StateMemento>();
    let threaded: StateMemento | undefined;
    for (const entry of this.entries) {
      const returned = entry.object.addMessage(message, threaded);
      threaded = returned ?? entry.object.emitStateMemento();
      mementos.set(entry.name, threaded);
    }

    return {
      accepted: true,
      rejectedBy: undefined,
      mementos,
      shouldPersist: true,
    };
  }

  stateDigests(): Map<string, string[]> {
    return new Map(
      this.entries.map((entry) => [entry.name, entry.object.getStateDigests()]),
    );
  }
}
