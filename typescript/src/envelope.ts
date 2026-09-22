/** Envelope — SPEC/wire-v1.md §3. */

import {
  type JsonValue,
  canonicalBytes,
  canonicalJson,
  hexToBytes,
  parseJson,
  payloadDigest,
} from './canonical.ts';
import { type SignatureAlgorithm, isAlgorithm, sign, verify } from './crypto.ts';
import { CanonicalError, ProtocolError } from './errors.ts';

export const PROTOCOL_VERSION = 1;
export const MAX_FUTURE_SKEW_MS = 300000; // 5 minutes

const ALLOWED_FIELDS = new Set(['v', 'type', 'data', 'id', 'ts', 'sig', 'pk', 'alg']);
const REQUIRED_FIELDS = ['v', 'type', 'data', 'id', 'ts'] as const;

const TYPE_RE = /^[a-z0-9._-]{1,64}$/;
const HEX64_RE = /^[0-9a-f]{64}$/;
const HEX128_RE = /^[0-9a-f]{128}$/;

export interface BuildOptions {
  readonly ts?: number;
  readonly sig?: string;
  readonly pk?: string;
  readonly alg?: SignatureAlgorithm;
}

export interface ParseOptions {
  /** Fixes the clock for the §3.4 future-timestamp check. */
  readonly nowMs?: number;
}

function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

export class Envelope {
  readonly v: number;
  readonly type: string;
  readonly data: JsonValue;
  readonly id: string;
  readonly ts: number;
  readonly sig: string | undefined;
  readonly pk: string | undefined;
  readonly alg: SignatureAlgorithm | undefined;

  private constructor(fields: {
    v: number;
    type: string;
    data: JsonValue;
    id: string;
    ts: number;
    sig?: string | undefined;
    pk?: string | undefined;
    alg?: SignatureAlgorithm | undefined;
  }) {
    this.v = fields.v;
    this.type = fields.type;
    this.data = fields.data;
    this.id = fields.id;
    this.ts = fields.ts;
    this.sig = fields.sig;
    this.pk = fields.pk;
    this.alg = fields.alg;
  }

  /** Build an envelope, computing the payload digest. */
  static build(type: string, data: JsonValue, options: BuildOptions = {}): Envelope {
    if (typeof type !== 'string' || !TYPE_RE.test(type)) {
      throw new ProtocolError(`invalid type: ${JSON.stringify(type)}`);
    }
    let id: string;
    try {
      id = payloadDigest(data);
    } catch (error) {
      throw new ProtocolError(
        error instanceof CanonicalError ? error.message : String(error),
      );
    }
    return new Envelope({
      v: PROTOCOL_VERSION,
      type,
      data,
      id,
      ts: options.ts ?? Date.now(),
      sig: options.sig,
      pk: options.pk,
      alg: options.alg,
    });
  }

  toObject(): Record<string, JsonValue> {
    const out: Record<string, JsonValue> = {
      v: this.v,
      type: this.type,
      data: this.data,
      id: this.id,
      ts: this.ts,
    };
    if (this.sig !== undefined) out['sig'] = this.sig;
    if (this.pk !== undefined) out['pk'] = this.pk;
    if (this.alg !== undefined) out['alg'] = this.alg;
    return out;
  }

  toJson(): string {
    return canonicalJson(this.toObject());
  }

  toBytes(): Uint8Array {
    return canonicalBytes(this.toObject());
  }

  /**
   * Validate and parse. Check order follows §3.3, cheapest first, because
   * signature verification is the only expensive step.
   */
  static parse(
    raw: string | Uint8Array | JsonValue,
    options: ParseOptions = {},
  ): Envelope {
    let source: JsonValue;
    if (raw instanceof Uint8Array) {
      let text: string;
      try {
        text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
      } catch {
        throw new ProtocolError('body is not valid UTF-8');
      }
      source = Envelope.parseText(text);
    } else if (typeof raw === 'string') {
      source = Envelope.parseText(raw);
    } else {
      source = raw;
    }

    if (source === null || typeof source !== 'object' || Array.isArray(source)) {
      throw new ProtocolError('envelope must be a JSON object');
    }
    const obj = source as Record<string, JsonValue>;

    const unknown = Object.keys(obj).filter((key) => !ALLOWED_FIELDS.has(key));
    if (unknown.length > 0) {
      throw new ProtocolError(
        `unknown envelope fields: ${JSON.stringify(unknown.sort())}`,
      );
    }
    const missing = REQUIRED_FIELDS.filter((key) => !(key in obj));
    if (missing.length > 0) {
      throw new ProtocolError(`missing envelope fields: ${JSON.stringify(missing)}`);
    }

    const version = obj['v'];
    if (!isInteger(version)) {
      throw new ProtocolError('v must be an integer');
    }
    if (version !== PROTOCOL_VERSION) {
      throw new ProtocolError(`unsupported protocol version: ${version}`);
    }

    const type = obj['type'];
    if (typeof type !== 'string' || !TYPE_RE.test(type)) {
      throw new ProtocolError(`invalid type: ${JSON.stringify(type)}`);
    }

    const ts = obj['ts'];
    if (!isInteger(ts)) {
      throw new ProtocolError('ts must be an integer');
    }
    if (ts < 0) {
      throw new ProtocolError('ts must be non-negative');
    }
    const reference = options.nowMs ?? Date.now();
    if (ts > reference + MAX_FUTURE_SKEW_MS) {
      throw new ProtocolError('ts is too far in the future');
    }

    const id = obj['id'];
    if (typeof id !== 'string' || !HEX64_RE.test(id)) {
      throw new ProtocolError('id must be 64 lowercase hex characters');
    }

    const data = obj['data'] as JsonValue;
    let computed: string;
    try {
      computed = payloadDigest(data);
    } catch (error) {
      throw new ProtocolError(
        error instanceof CanonicalError ? error.message : String(error),
      );
    }
    if (computed !== id) {
      throw new ProtocolError('id does not match the payload digest');
    }

    const sig = obj['sig'];
    const pk = obj['pk'];
    const alg = obj['alg'];
    if (sig !== undefined) {
      if (typeof sig !== 'string' || !HEX128_RE.test(sig)) {
        throw new ProtocolError('sig must be 128 lowercase hex characters');
      }
      if (typeof pk !== 'string' || !HEX64_RE.test(pk)) {
        throw new ProtocolError('pk must be 64 lowercase hex characters');
      }
      if (!isAlgorithm(alg)) {
        throw new ProtocolError('alg must be one of ["ed25519","schnorr"]');
      }
    } else if (pk !== undefined || alg !== undefined) {
      throw new ProtocolError('pk and alg require sig');
    }

    return new Envelope({
      v: version,
      type,
      data,
      id,
      ts,
      sig: typeof sig === 'string' ? sig : undefined,
      pk: typeof pk === 'string' ? pk : undefined,
      alg: isAlgorithm(alg) ? alg : undefined,
    });
  }

  private static parseText(text: string): JsonValue {
    try {
      return parseJson(text);
    } catch (error) {
      throw new ProtocolError(
        error instanceof CanonicalError ? error.message : String(error),
      );
    }
  }

  /** The 32 raw bytes signed: the hex-decoded id, never hashed again — §6. */
  signingBytes(): Uint8Array {
    return hexToBytes(this.id);
  }

  /** Verify the signature. False when absent or malformed. */
  verify(): boolean {
    if (this.sig === undefined || this.pk === undefined || this.alg === undefined) {
      return false;
    }
    try {
      return verify(
        this.alg,
        this.signingBytes(),
        hexToBytes(this.sig),
        hexToBytes(this.pk),
      );
    } catch {
      return false;
    }
  }

  /** A copy carrying a signature over this envelope's id. */
  signed(
    alg: SignatureAlgorithm,
    secretKey: Uint8Array,
    aux?: Uint8Array,
  ): Envelope {
    const result =
      aux === undefined
        ? sign(alg, this.signingBytes(), secretKey)
        : sign(alg, this.signingBytes(), secretKey, aux);
    const toHex = (bytes: Uint8Array): string =>
      Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    return new Envelope({
      v: this.v,
      type: this.type,
      data: this.data,
      id: this.id,
      ts: this.ts,
      sig: toHex(result.signature),
      pk: toHex(result.publicKey),
      alg,
    });
  }

  path(): 'control' | 'gossip' {
    if (this.type.startsWith('ctl.') || this.type.startsWith('link.')) return 'control';
    return 'gossip';
  }

  isControl(): boolean {
    return this.path() === 'control';
  }
}
