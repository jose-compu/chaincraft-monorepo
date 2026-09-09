/**
 * Error classes.
 *
 * Parity is of error *class*, not of error type or message: where Python raises
 * `CanonicalError`, this throws `CanonicalError`. Messages are free to differ.
 */

export class ChaincraftError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

/** A value cannot be represented as canonical JSON — wire-v1 §1. */
export class CanonicalError extends ChaincraftError {}

/** An envelope or control message violates the wire protocol — wire-v1 §3, §5. */
export class ProtocolError extends ChaincraftError {}

/** A frame violates the framing rules — wire-v1 §4. */
export class FramingError extends ChaincraftError {}
