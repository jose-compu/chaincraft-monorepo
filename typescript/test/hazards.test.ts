/**
 * JavaScript-specific hazards.
 *
 * The shared vectors cover normative behaviour and are the real contract. This
 * file pins the traps that are particular to this runtime — the places where a
 * reasonable-looking JavaScript implementation silently diverges. Each test
 * names the spec rule it protects.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  CanonicalError,
  ChaincraftError,
  Envelope,
  FrameReader,
  FramingError,
  MAX_DEPTH,
  MAX_SAFE_INT,
  MIN_SAFE_INT,
  ProtocolError,
  SCHNORR,
  StateMemento,
  canonicalJson,
  compareCodePoints,
  control,
  hexToBytes,
  parseJson,
  payloadDigest,
} from '../src/index.ts';
import { Counter, buildRegistry, snapshot } from './conformanceObjects.ts';

// --- §1.1.1 code point order is not UTF-16 code unit order ------------------

test('code point comparator disagrees with the default comparator', () => {
  const keys = ['\u{10000}', '\uE000'];
  assert.deepEqual([...keys].sort(), ['\u{10000}', '\uE000'], 'default is code unit order');
  assert.deepEqual(
    [...keys].sort(compareCodePoints),
    ['\uE000', '\u{10000}'],
    'canonical JSON requires code point order',
  );
});

test('astral keys are emitted in code point order', () => {
  const text = canonicalJson({ '\u{10000}': 2, '\uE000': 1 });
  assert.equal(text.indexOf('\uE000') < text.indexOf('\u{10000}'), true);
});

test('comparator orders a prefix before its extension', () => {
  assert.equal(compareCodePoints('a', 'ab') < 0, true);
  assert.equal(compareCodePoints('ab', 'a') > 0, true);
  assert.equal(compareCodePoints('a', 'a'), 0);
});

// --- §1.3.1 the float restriction is lexical --------------------------------

test('JSON.parse cannot satisfy the float rule, which is why we do not use it', () => {
  // The premise of the spec rule: the platform parser destroys the evidence.
  assert.equal(JSON.parse('1e3'), 1000);
  assert.equal(Number.isSafeInteger(JSON.parse('1e3')), true);
  // Our parser inspects the token instead.
  assert.throws(() => parseJson('1e3'), CanonicalError);
});

test('integer-valued float tokens are rejected', () => {
  for (const token of ['1.0', '-0.0', '1e2', '1E2', '0.0']) {
    assert.throws(() => parseJson(token), CanonicalError, token);
  }
});

test('genuine integers are accepted', () => {
  assert.equal(parseJson('0'), 0);
  assert.equal(parseJson('-42'), -42);
  assert.equal(parseJson(String(MAX_SAFE_INT)), MAX_SAFE_INT);
  assert.equal(parseJson(String(MIN_SAFE_INT)), MIN_SAFE_INT);
});

test('integers beyond the safe range are rejected', () => {
  assert.throws(() => parseJson('9007199254740992'), CanonicalError);
  assert.throws(() => parseJson('-9007199254740992'), CanonicalError);
});

test('leading zeros are rejected', () => {
  assert.throws(() => parseJson('01'), CanonicalError);
  assert.throws(() => parseJson('-01'), CanonicalError);
});

test('negative zero encodes as zero', () => {
  assert.equal(canonicalJson(-0), '0');
  assert.equal(canonicalJson({ a: -0 }), '{"a":0}');
});

// --- §1.1 rule 2 duplicate keys --------------------------------------------

test('JSON.parse keeps the last duplicate, which is why we do not use it', () => {
  assert.deepEqual(JSON.parse('{"a":1,"a":2}'), { a: 2 });
  assert.throws(() => parseJson('{"a":1,"a":2}'), CanonicalError);
});

test('duplicate keys are rejected at any depth', () => {
  assert.throws(() => parseJson('{"o":{"a":1,"a":2}}'), CanonicalError);
});

// --- §1.1 rule 3 and 4 strings ---------------------------------------------

test('surrogate pairs decode to one code point', () => {
  assert.equal(parseJson('"\\ud83d\\ude00"'), '\u{1f600}');
  assert.equal(canonicalJson('\u{1f600}'), '"\u{1f600}"');
});

test('lone surrogates are rejected', () => {
  assert.throws(() => parseJson('"\\ud800"'), CanonicalError);
  assert.throws(() => parseJson('"\\udc00"'), CanonicalError);
  assert.throws(() => parseJson('"\\ud800a"'), CanonicalError);
  assert.throws(() => canonicalJson('\ud800'), CanonicalError);
});

test('unescaped control characters are rejected on parse', () => {
  assert.throws(() => parseJson('"a\u0001b"'), CanonicalError);
});

test('solidus round-trips unescaped', () => {
  assert.equal(canonicalJson(parseJson('"a\\/b"')), '"a/b"');
});

// --- §1.4 nesting limit -----------------------------------------------------

test('nesting at the limit is accepted and beyond it is rejected', () => {
  const nest = (depth: number): string => '['.repeat(depth) + '1' + ']'.repeat(depth);
  assert.doesNotThrow(() => parseJson(nest(MAX_DEPTH - 1)));
  assert.throws(() => parseJson(nest(MAX_DEPTH + 5)), CanonicalError);

  let deep: unknown = 1;
  for (let i = 0; i < MAX_DEPTH + 5; i++) deep = [deep];
  assert.throws(() => canonicalJson(deep), CanonicalError);
});

// --- §2 content addressing --------------------------------------------------

test('digest ignores key order and envelope timestamp', () => {
  assert.equal(payloadDigest({ a: 1, b: 2 }), payloadDigest({ b: 2, a: 1 }));
  const early = Envelope.build('app.t', { n: 1 }, { ts: 1 });
  const late = Envelope.build('app.t', { n: 1 }, { ts: 999 });
  assert.equal(early.id, late.id);
});

test('re-serializing an envelope preserves its digest', () => {
  const original = Envelope.build('app.t', { z: 1, a: [1, 2] }, { ts: 1757430000000 });
  const relayed = Envelope.parse(original.toJson(), { nowMs: 1757430000000 });
  const rebuilt = Envelope.build('app.t', relayed.data, { ts: relayed.ts });
  assert.equal(rebuilt.id, original.id);
  assert.equal(rebuilt.toJson(), original.toJson());
});

// --- §4 framing -------------------------------------------------------------

test('frame reader reassembles a stream fed one byte at a time', () => {
  const body = new TextEncoder().encode('{"a":1}');
  const frame = new Uint8Array([0, 0, 0, body.length, ...body]);
  const reader = new FrameReader();
  const received: Uint8Array[] = [];
  for (const byte of frame) {
    received.push(...reader.feed(new Uint8Array([byte])));
  }
  assert.equal(received.length, 1);
  assert.deepEqual(received[0], body);
  assert.equal(reader.pending, 0);
});

test('frame reader buffers a partial frame without emitting it', () => {
  const reader = new FrameReader();
  assert.deepEqual(reader.feed(new Uint8Array([0, 0, 0, 5, 97, 98])), []);
  assert.equal(reader.pending, 6);
});

test('oversize declared length is rejected before the body arrives', () => {
  const reader = new FrameReader();
  assert.throws(() => reader.feed(new Uint8Array([0x01, 0x00, 0x00, 0x01])), FramingError);
});

// --- §5.1 capability sorting ------------------------------------------------

test('hello sorts and deduplicates caps so the digest is stable', () => {
  const a = control.hello('ts/1.0', { caps: ['udp', 'gossip', 'udp'], ts: 1 });
  const b = control.hello('ts/1.0', { caps: ['gossip', 'udp'], ts: 1 });
  assert.equal(a.id, b.id, 'the same capability set must be the same message');
  assert.deepEqual((a.data as Record<string, unknown>)['caps'], ['gossip', 'udp']);
});

test('hello rejects a version we cannot serve', () => {
  const env = Envelope.build(control.HELLO, { v: 99, impl: 'x/1', caps: [] }, { ts: 1 });
  assert.throws(() => control.parseHello(env), ProtocolError);
});

test('unknown capabilities are reported, not rejected', () => {
  const env = control.hello('ts/1.0', { caps: ['gossip', 'warp-drive'], ts: 1 });
  const parsed = control.parseHello(env);
  assert.deepEqual(parsed.caps, ['gossip']);
  assert.deepEqual(parsed.unknownCaps, ['warp-drive']);
});

// --- §6 signatures ----------------------------------------------------------

test('a signed envelope round-trips and verifies', () => {
  const signed = Envelope.build('app.t', { n: 1 }, { ts: 1 }).signed(
    SCHNORR,
    hexToBytes('00'.repeat(31) + '03'),
  );
  assert.ok(signed.verify());
  assert.ok(Envelope.parse(signed.toJson(), { nowMs: 1 }).verify());
});

test('a swapped public key reads as invalid rather than throwing', () => {
  const signed = Envelope.build('app.t', { n: 1 }, { ts: 1 }).signed(
    SCHNORR,
    hexToBytes('00'.repeat(31) + '03'),
  );
  const tampered = Envelope.parse(
    { ...signed.toObject(), pk: 'ab'.repeat(32) },
    { nowMs: 1 },
  );
  assert.equal(tampered.verify(), false);
});

test('an unsigned envelope does not claim to verify', () => {
  assert.equal(Envelope.build('app.t', { n: 1 }, { ts: 1 }).verify(), false);
});

// --- error classes ----------------------------------------------------------

test('error classes share a base and keep their names', () => {
  for (const error of [
    new CanonicalError('x'),
    new ProtocolError('x'),
    new FramingError('x'),
  ]) {
    assert.ok(error instanceof ChaincraftError);
    assert.ok(error instanceof Error);
  }
  assert.equal(new CanonicalError('x').name, 'CanonicalError');
  assert.equal(new ProtocolError('x').name, 'ProtocolError');
  assert.equal(new FramingError('x').name, 'FramingError');
});

// --- Level 1 ----------------------------------------------------------------

test('memento serializes with snake_case keys for the shared format', () => {
  const memento = StateMemento.normalize('a'.repeat(64), []);
  assert.deepEqual(Object.keys(memento.toObject()).sort(), [
    'canonical_digest',
    'frontier_digests',
    'metadata',
    'revision',
  ]);
});

test('an object returning undefined falls back to emitStateMemento', () => {
  const result = buildRegistry().apply({ delta: 1, seq: 1 });
  assert.ok(result.accepted);
  const mirror = result.mementos.get('mirror');
  assert.ok(mirror !== undefined);
  assert.equal(mirror.canonicalDigest, '', 'mirror is not merkelized');
});

test('a rejected message leaves every object untouched', () => {
  const registry = buildRegistry();
  registry.apply({ delta: 5, seq: 1 });
  const before = snapshot(registry);
  const result = registry.apply({ delta: 5, seq: 99 });
  assert.equal(result.accepted, false);
  assert.equal(result.rejectedBy, 'counter');
  assert.deepEqual(snapshot(registry), before);
});

test('registration order is reported and enforced as unique', () => {
  const registry = buildRegistry();
  assert.deepEqual(registry.names, ['counter', 'mirror']);
  assert.throws(() => registry.register('counter', new Counter()));
});

test('node listen defaults to 0.0.0.0:9735', async () => {
  const { DEFAULT_LISTEN, MAX_PEERS, parseListen } = await import('../src/mesh.ts');
  assert.equal(DEFAULT_LISTEN, '0.0.0.0:9735');
  assert.equal(MAX_PEERS, 256);
  assert.deepEqual(parseListen(), { host: '0.0.0.0', port: 9735 });
  assert.deepEqual(parseListen('127.0.0.1:0'), { host: '127.0.0.1', port: 0 });
  assert.deepEqual(parseListen('127.0.0.1:9736'), { host: '127.0.0.1', port: 9736 });
  assert.throws(() => parseListen('9735'));
});
