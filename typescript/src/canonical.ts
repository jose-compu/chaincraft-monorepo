/**
 * Canonical JSON — SPEC/wire-v1.md §1.
 *
 * This module carries its own JSON parser. `JSON.parse` is not usable here for
 * two independent reasons, both spelled out in the spec:
 *
 *   - §1.3.1 rejects float *tokens*, but `JSON.parse('1e3')` yields `1000`,
 *     destroying the evidence before it can be checked.
 *   - §1.1 rule 2 rejects duplicate keys, which `JSON.parse` silently resolves
 *     by keeping the last one.
 *
 * Both would fail silently rather than loudly, which is the failure mode the
 * whole canonicalization exercise exists to prevent.
 */

import { sha256 } from '@noble/hashes/sha2.js';
import { CanonicalError } from './errors.ts';

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export const MAX_SAFE_INT = 9007199254740991; // 2**53 - 1
export const MIN_SAFE_INT = -9007199254740991;
export const MAX_DEPTH = 100;

// -------------------------------------------------------------------------
// §1.1.1 — code point ordering
// -------------------------------------------------------------------------

/**
 * Compare by Unicode code point, not by UTF-16 code unit.
 *
 * The default comparator would order a surrogate pair below U+E000..U+FFFF;
 * code point order puts it above. See wire-v1 §1.1.1.
 */
export function compareCodePoints(a: string, b: string): number {
  const left = Array.from(a);
  const right = Array.from(b);
  const shared = Math.min(left.length, right.length);
  for (let i = 0; i < shared; i++) {
    const x = left[i]!.codePointAt(0)!;
    const y = right[i]!.codePointAt(0)!;
    if (x !== y) return x < y ? -1 : 1;
  }
  return left.length - right.length;
}

// -------------------------------------------------------------------------
// §1.1 rule 4 — string escaping
// -------------------------------------------------------------------------

const ESCAPES = new Map<string, string>([
  ['"', '\\"'],
  ['\\', '\\\\'],
  ['\b', '\\b'],
  ['\t', '\\t'],
  ['\n', '\\n'],
  ['\f', '\\f'],
  ['\r', '\\r'],
]);

function encodeString(value: string): string {
  let out = '"';
  for (const ch of value) {
    const escaped = ESCAPES.get(ch);
    if (escaped !== undefined) {
      out += escaped;
    } else if (ch < '\u0020') {
      out += '\\u' + ch.codePointAt(0)!.toString(16).padStart(4, '0');
    } else {
      const code = ch.codePointAt(0)!;
      if (code >= 0xd800 && code <= 0xdfff) {
        throw new CanonicalError('lone surrogate in string');
      }
      out += ch;
    }
  }
  return out + '"';
}

// -------------------------------------------------------------------------
// Encoding
// -------------------------------------------------------------------------

function encode(value: unknown, out: string[], depth: number): void {
  if (depth > MAX_DEPTH) {
    throw new CanonicalError('value nested too deeply');
  }

  if (value === null) {
    out.push('null');
    return;
  }

  switch (typeof value) {
    case 'boolean':
      out.push(value ? 'true' : 'false');
      return;

    case 'number': {
      if (!Number.isFinite(value)) {
        throw new CanonicalError('non-finite numbers are not valid JSON');
      }
      if (!Number.isInteger(value)) {
        throw new CanonicalError(
          'floating-point numbers are not permitted in wire v1; ' +
            'use a scaled integer or a string',
        );
      }
      if (value < MIN_SAFE_INT || value > MAX_SAFE_INT) {
        throw new CanonicalError(`integer ${value} outside the safe range`);
      }
      // Normalizes -0 to 0, since -0 === 0.
      out.push(value === 0 ? '0' : String(value));
      return;
    }

    case 'string':
      out.push(encodeString(value));
      return;

    case 'bigint':
      throw new CanonicalError('bigint is not JSON representable');

    case 'object':
      break;

    default:
      throw new CanonicalError(`${typeof value} is not JSON representable`);
  }

  if (Array.isArray(value)) {
    out.push('[');
    for (let i = 0; i < value.length; i++) {
      if (i > 0) out.push(',');
      encode(value[i], out, depth + 1);
    }
    out.push(']');
    return;
  }

  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort(compareCodePoints);
  out.push('{');
  for (let i = 0; i < keys.length; i++) {
    if (i > 0) out.push(',');
    const key = keys[i]!;
    out.push(encodeString(key));
    out.push(':');
    encode(record[key], out, depth + 1);
  }
  out.push('}');
}

/** Serialize to canonical JSON text — wire-v1 §1. */
export function canonicalJson(value: unknown): string {
  const out: string[] = [];
  encode(value, out, 0);
  return out.join('');
}

/** Serialize to canonical JSON, UTF-8 encoded. */
export function canonicalBytes(value: unknown): Uint8Array {
  return new TextEncoder().encode(canonicalJson(value));
}

// -------------------------------------------------------------------------
// §2 — payload digest
// -------------------------------------------------------------------------

const HEX = '0123456789abcdef';

export function bytesToHex(bytes: Uint8Array): string {
  let out = '';
  for (const byte of bytes) {
    out += HEX[byte >> 4]! + HEX[byte & 0x0f]!;
  }
  return out;
}

export function hexToBytes(hex: string): Uint8Array {
  if (hex.length % 2 !== 0) {
    throw new CanonicalError('hex string has an odd length');
  }
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    const byte = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
    if (Number.isNaN(byte)) {
      throw new CanonicalError('invalid hex string');
    }
    out[i] = byte;
  }
  return out;
}

/** Payload digest — wire-v1 §2. Lowercase hex sha256 over canonical bytes. */
export function payloadDigest(data: unknown): string {
  return bytesToHex(sha256(canonicalBytes(data)));
}

// -------------------------------------------------------------------------
// Parsing
// -------------------------------------------------------------------------

const WHITESPACE = new Set([' ', '\t', '\n', '\r']);

class Parser {
  private pos = 0;
  private readonly text: string;

  // Written out rather than as a parameter property: Node's strip-only
  // TypeScript mode rejects parameter properties, since they emit code.
  constructor(text: string) {
    this.text = text;
  }

  parse(): JsonValue {
    this.skipWhitespace();
    const value = this.value(0);
    this.skipWhitespace();
    if (this.pos < this.text.length) {
      this.fail(`unexpected trailing content`);
    }
    return value;
  }

  private fail(message: string): never {
    throw new CanonicalError(`${message} at position ${this.pos}`);
  }

  private peek(): string | undefined {
    return this.text[this.pos];
  }

  private skipWhitespace(): void {
    while (this.pos < this.text.length && WHITESPACE.has(this.text[this.pos]!)) {
      this.pos++;
    }
  }

  private expect(char: string): void {
    if (this.text[this.pos] !== char) {
      this.fail(`expected ${JSON.stringify(char)}`);
    }
    this.pos++;
  }

  private value(depth: number): JsonValue {
    if (depth > MAX_DEPTH) {
      this.fail('value nested too deeply');
    }
    const ch = this.peek();
    if (ch === undefined) this.fail('unexpected end of input');
    if (ch === '{') return this.object(depth);
    if (ch === '[') return this.array(depth);
    if (ch === '"') return this.string();
    if (ch === 't') return this.literal('true', true);
    if (ch === 'f') return this.literal('false', false);
    if (ch === 'n') return this.literal('null', null);
    if (ch === '-' || (ch >= '0' && ch <= '9')) return this.number();
    this.fail(`unexpected character ${JSON.stringify(ch)}`);
  }

  private literal<T extends boolean | null>(token: string, value: T): T {
    if (this.text.startsWith(token, this.pos)) {
      this.pos += token.length;
      return value;
    }
    // NaN and Infinity land here, and are not valid JSON.
    this.fail('invalid literal');
  }

  private isDigit(ch: string | undefined): boolean {
    return ch !== undefined && ch >= '0' && ch <= '9';
  }

  /**
   * §1.2 and §1.3.1 — integers only, and the check is on the token.
   *
   * A fraction or exponent is rejected here even when the value would be an
   * integer, because by the time a number reaches JavaScript's numeric type the
   * distinction is gone.
   */
  private number(): number {
    const start = this.pos;
    if (this.peek() === '-') this.pos++;

    if (this.peek() === '0') {
      this.pos++;
      if (this.isDigit(this.peek())) {
        this.fail('leading zeros are not valid JSON');
      }
    } else if (this.isDigit(this.peek())) {
      while (this.isDigit(this.peek())) this.pos++;
    } else {
      this.fail('invalid number');
    }

    const next = this.peek();
    if (next === '.' || next === 'e' || next === 'E') {
      this.fail('floating-point numbers are not permitted in wire v1');
    }

    const token = this.text.slice(start, this.pos);
    const value = Number(token);
    if (!Number.isSafeInteger(value)) {
      this.fail(`integer ${token} outside the safe range`);
    }
    return value;
  }

  private string(): string {
    this.expect('"');
    let out = '';
    for (;;) {
      const ch = this.text[this.pos];
      if (ch === undefined) this.fail('unterminated string');
      if (ch === '"') {
        this.pos++;
        return out;
      }
      if (ch === '\\') {
        this.pos++;
        out += this.escape();
        continue;
      }
      if (ch < '\u0020') {
        this.fail('unescaped control character in string');
      }
      out += ch;
      this.pos++;
    }
  }

  private escape(): string {
    const ch = this.text[this.pos];
    if (ch === undefined) this.fail('unterminated escape');
    this.pos++;
    switch (ch) {
      case '"':
        return '"';
      case '\\':
        return '\\';
      case '/':
        return '/';
      case 'b':
        return '\b';
      case 'f':
        return '\f';
      case 'n':
        return '\n';
      case 'r':
        return '\r';
      case 't':
        return '\t';
      case 'u':
        return this.unicodeEscape();
      default:
        this.fail(`invalid escape \\${ch}`);
    }
  }

  private hex4(): number {
    const digits = this.text.slice(this.pos, this.pos + 4);
    if (digits.length !== 4 || !/^[0-9a-fA-F]{4}$/.test(digits)) {
      this.fail('invalid \\u escape');
    }
    this.pos += 4;
    return Number.parseInt(digits, 16);
  }

  /** A high surrogate must be followed by a low one; lone surrogates fail. */
  private unicodeEscape(): string {
    const first = this.hex4();
    if (first >= 0xdc00 && first <= 0xdfff) {
      this.fail('lone low surrogate');
    }
    if (first >= 0xd800 && first <= 0xdbff) {
      if (this.text[this.pos] !== '\\' || this.text[this.pos + 1] !== 'u') {
        this.fail('lone high surrogate');
      }
      this.pos += 2;
      const second = this.hex4();
      if (second < 0xdc00 || second > 0xdfff) {
        this.fail('high surrogate not followed by a low surrogate');
      }
      return String.fromCodePoint(
        0x10000 + ((first - 0xd800) << 10) + (second - 0xdc00),
      );
    }
    return String.fromCharCode(first);
  }

  private array(depth: number): JsonValue[] {
    this.expect('[');
    const out: JsonValue[] = [];
    this.skipWhitespace();
    if (this.peek() === ']') {
      this.pos++;
      return out;
    }
    for (;;) {
      this.skipWhitespace();
      out.push(this.value(depth + 1));
      this.skipWhitespace();
      const ch = this.peek();
      if (ch === ',') {
        this.pos++;
        continue;
      }
      if (ch === ']') {
        this.pos++;
        return out;
      }
      this.fail('expected "," or "]"');
    }
  }

  private object(depth: number): { [key: string]: JsonValue } {
    this.expect('{');
    const out: { [key: string]: JsonValue } = Object.create(null) as {
      [key: string]: JsonValue;
    };
    const seen = new Set<string>();
    this.skipWhitespace();
    if (this.peek() === '}') {
      this.pos++;
      return { ...out };
    }
    for (;;) {
      this.skipWhitespace();
      if (this.peek() !== '"') this.fail('expected an object key');
      const key = this.string();
      if (seen.has(key)) {
        this.fail(`duplicate object key ${JSON.stringify(key)}`);
      }
      seen.add(key);
      this.skipWhitespace();
      this.expect(':');
      this.skipWhitespace();
      out[key] = this.value(depth + 1);
      this.skipWhitespace();
      const ch = this.peek();
      if (ch === ',') {
        this.pos++;
        continue;
      }
      if (ch === '}') {
        this.pos++;
        // Spread onto a normal object so consumers see a conventional prototype.
        return { ...out };
      }
      this.fail('expected "," or "}"');
    }
  }
}

/**
 * Parse JSON, enforcing the canonical-JSON restrictions on the way in.
 *
 * Rejects duplicate keys (§1.1 rule 2), float tokens (§1.3.1), integers outside
 * the safe range (§1.2), lone surrogates and excessive nesting (§1.4).
 */
export function parseJson(text: string): JsonValue {
  return new Parser(text).parse();
}
