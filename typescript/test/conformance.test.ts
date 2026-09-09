/**
 * Conformance vectors — the shared cross-language contract.
 *
 * Every implementation runs these same files. A failure here is a wire protocol
 * violation, not a local bug. Never edit a vector to make a test pass; see
 * AGENTS.md §7.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  AddressBook,
  CanonicalError,
  PBFT,
  ProofOfStake,
  ProofOfWork,
  BalanceLedger,
  UtxoLedger,
  Mempool,
  Deduplicator,
  fees,
  LocalDiscovery,
  Envelope,
  FrameReader,
  FramingError,
  ProtocolError,
  StateMemento,
  canonicalJson,
  control,
  ecdsa,
  decodeDatagram,
  encodeDatagram,
  encodeFrame,
  frontierDigest,
  hexToBytes,
  isValidAddress,
  merkleDigest,
  parseJson,
  payloadDigest,
  publicKeyHex,
  sign,
  vdf,
  verify,
  vrf,
  winsReplacement,
} from '../src/index.ts';
import { buildRegistry, snapshot } from './conformanceObjects.ts';

const VECTORS = join(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
  'conformance',
  'vectors',
);

type Case = Record<string, any>;

function load(name: string): Record<string, any> {
  return JSON.parse(readFileSync(join(VECTORS, name), 'utf8'));
}

function bytes(hex: string): Uint8Array {
  return hexToBytes(hex);
}

function toHex(data: Uint8Array): string {
  return Array.from(data, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** Run one node:test per case so a failure names the case, as pytest does. */
function eachCase(
  file: string,
  section: string,
  run: (c: Case, doc: Record<string, any>) => void,
): void {
  const doc = load(file);
  const cases: Case[] = doc[section] ?? [];
  assert.ok(cases.length > 0, `${file} has no ${section} cases`);
  for (const [index, entry] of cases.entries()) {
    test(`${file} ${section}: ${entry['name'] ?? index}`, () => run(entry, doc));
  }
}

// --- wire.canonical-json ----------------------------------------------------

eachCase('canonical-json.json', 'valid', (c) => {
  assert.equal(canonicalJson(parseJson(c['input_json'])), c['canonical']);
});

eachCase('canonical-json.json', 'invalid', (c) => {
  assert.throws(
    () => canonicalJson(parseJson(c['input_json'])),
    CanonicalError,
    c['reason'],
  );
});

// --- wire.payload-digest ----------------------------------------------------

eachCase('digest.json', 'valid', (c) => {
  const data = parseJson(c['data_json']);
  assert.equal(canonicalJson(data), c['canonical']);
  assert.equal(payloadDigest(data), c['digest']);
});

// --- wire.envelope ----------------------------------------------------------

eachCase('envelope.json', 'valid', (c, doc) => {
  const env = Envelope.build(c['type'], parseJson(c['data_json']), { ts: c['ts'] });
  assert.equal(env.id, c['id']);
  assert.equal(env.toJson(), c['canonical']);

  const parsed = Envelope.parse(c['canonical'], { nowMs: doc['now_ms'] });
  assert.equal(parsed.toJson(), c['canonical']);
});

eachCase('envelope.json', 'invalid', (c, doc) => {
  assert.throws(
    () => Envelope.parse(c['envelope_json'], { nowMs: doc['now_ms'] }),
    ProtocolError,
    c['reason'],
  );
});

// --- wire.framing-tcp -------------------------------------------------------

eachCase('framing.json', 'valid', (c) => {
  assert.equal(toHex(encodeFrame(bytes(c['body_hex']))), c['frame_hex']);
});

eachCase('framing.json', 'stream', (c) => {
  const reader = new FrameReader();
  const received: Uint8Array[] = [];
  for (const chunk of c['chunks_hex'] as string[]) {
    received.push(...reader.feed(bytes(chunk)));
  }
  assert.deepEqual(received.map(toHex), c['frames_hex']);
});

eachCase('framing.json', 'invalid', (c) => {
  assert.throws(
    () => new FrameReader().feed(bytes(c['input_hex'])),
    FramingError,
    c['reason'],
  );
});

// --- wire.framing-udp -------------------------------------------------------
//
// Registered as exempt for TypeScript because browsers have no raw UDP socket.
// The size-bound checks are pure and portable, so they run anyway: the exemption
// covers the transport, not the framing rules.

eachCase('framing.json', 'udp_valid', (c) => {
  const body = bytes(c['body_hex']);
  assert.deepEqual(encodeDatagram(body), body);
  assert.deepEqual(decodeDatagram(body), body);
});

eachCase('framing.json', 'udp_invalid', (c) => {
  const data =
    c['input_hex'] === null
      ? new Uint8Array(c['input_length'])
      : bytes(c['input_hex']);
  assert.throws(() => decodeDatagram(data), FramingError, c['reason']);
  assert.throws(() => encodeDatagram(data), FramingError, c['reason']);
});

// --- wire.control, wire.version-negotiation ---------------------------------

const CONTROL_BUILDERS: Record<string, (ts: number) => Envelope> = {
  'hello minimal': (ts) => control.hello('py-chaincraft/1.0.0', { ts }),
  'hello with listen and caps': (ts) =>
    control.hello('py-chaincraft/1.0.0', {
      caps: ['udp', 'gossip', 'digest-sync'],
      listen: '10.0.0.2:9735',
      ts,
    }),
  'peers request': (ts) => control.peersRequest({ ts }),
  'peers response': (ts) => control.peers(['10.0.0.2:9735', '10.0.0.3:9735'], { ts }),
  'digest request': (ts) => control.digestRequest('BalanceLedger', { ts }),
  'digest response': (ts) =>
    control.digest('BalanceLedger', 'ab'.repeat(32), ['cd'.repeat(32)], { ts }),
  'messages request': (ts) =>
    control.messagesRequest('BalanceLedger', 'ab'.repeat(32), { ts }),
  'messages response': (ts) =>
    control.messages('BalanceLedger', [Envelope.build('app.t', { n: 1 }, { ts })], {
      ts,
    }),
};

eachCase('control.json', 'valid', (c, doc) => {
  const parsed = Envelope.parse(c['canonical'], { nowMs: doc['now_ms'] });
  assert.equal(parsed.type, c['type']);
  assert.equal(parsed.id, c['id']);

  const builder = CONTROL_BUILDERS[c['name']];
  assert.ok(builder !== undefined, `no builder registered for ${c['name']}`);
  assert.equal(builder(parsed.ts).toJson(), c['canonical']);
});

eachCase('control.json', 'invalid', (c, doc) => {
  const env = Envelope.parse(c['envelope_json'], { nowMs: doc['now_ms'] });
  assert.throws(() => control.parseHello(env), ProtocolError, c['reason']);
});

// --- wire.sig-schnorr, wire.sig-ed25519 -------------------------------------

eachCase('signatures.json', 'valid', (c) => {
  const secretKey = bytes(c['secret_key']);
  const message = bytes(c['message']);

  assert.equal(publicKeyHex(c['alg'], secretKey), c['public_key']);

  const produced = sign(c['alg'], message, secretKey, bytes(c['aux']));
  assert.equal(
    toHex(produced.signature),
    c['signature'],
    'deterministic signing must match',
  );
  assert.ok(verify(c['alg'], message, produced.signature, bytes(c['public_key'])));

  if (c['canonical'] !== undefined) {
    const env = Envelope.parse(c['canonical'], { nowMs: 1e13 });
    assert.ok(env.verify());
  }
});

eachCase('signatures.json', 'invalid', (c) => {
  // Verification returns false on bad input and never throws into receive.
  const result = verify(
    c['alg'],
    bytes(c['message']),
    bytes(c['signature']),
    bytes(c['public_key']),
  );
  assert.equal(result, false);
});

// --- wire.dedup -------------------------------------------------------------

eachCase('dedup.json', 'sequence', (c, doc) => {
  // The eviction case only distinguishes FIFO-by-first-insertion from a policy
  // that refreshes on re-see if each step is checked in order.
  const dedup = new Deduplicator(c['capacity']);
  for (const [index, step] of (c['steps'] as Case[]).entries()) {
    const env = Envelope.parse(step['canonical'], { nowMs: doc['now_ms'] });
    const where = `step ${index} (${step['type']} ${String(step['id']).slice(0, 8)})`;
    assert.equal(env.id, step['id'], where);
    assert.equal(dedup.shouldProcess(env), step['should_process'], where);
    assert.equal(dedup.shouldRelay(env), step['should_relay'], where);
    assert.equal(dedup.seen.size, step['seen_size'], where);
  }
});

// --- object.memento, object.merkle-digest -----------------------------------

eachCase('memento.json', 'normalize', (c) => {
  const memento = StateMemento.normalize(
    c['input']['canonical_digest'],
    c['input']['frontier_digests'],
  );
  assert.deepEqual(memento.toObject(), c['expected']);
});

eachCase('memento.json', 'reorg', (c) => {
  const current = StateMemento.normalize(
    c['current']['canonical_digest'],
    c['current']['frontier_digests'],
  );
  const previous =
    c['previous'] === null
      ? undefined
      : StateMemento.normalize(
          c['previous']['canonical_digest'],
          c['previous']['frontier_digests'],
        );
  assert.equal(current.indicatesReorgAgainst(previous), c['expected']);
});

eachCase('memento.json', 'merkle', (c) => {
  const payload = parseJson(c['payload_json']);
  assert.equal(canonicalJson(payload), c['canonical']);
  assert.equal(merkleDigest(payload), c['digest']);
});

eachCase('memento.json', 'frontier', (c) => {
  assert.equal(frontierDigest(c['heads']), c['digest']);
});

// --- object.pipeline, object.contract, object.tiebreak ----------------------

eachCase('pipeline.json', 'replay', (c, doc) => {
  assert.deepEqual(doc['registry'], buildRegistry().names);

  const registry = buildRegistry();
  for (const [index, step] of (c['steps'] as Case[]).entries()) {
    const result = registry.apply(parseJson(step['message_json']));
    const where = `step ${index} (${step['message_json']})`;
    assert.equal(result.accepted, step['accepted'], where);
    assert.equal(result.rejectedBy ?? null, step['rejected_by'], where);
    assert.deepEqual(
      snapshot(registry),
      { counter: step['counter'], mirror: step['mirror'] },
      where,
    );
  }
});

eachCase('pipeline.json', 'tiebreak', (c) => {
  assert.equal(
    winsReplacement(
      c['candidate']['rank'],
      c['candidate']['digest'],
      c['incumbent']['rank'],
      c['incumbent']['digest'],
    ),
    c['expected'],
  );
});

eachCase('ecdsa.json', 'valid', (c) => {
  const key = bytes(c['secret_key']);
  const message = bytes(c['message_hex']);
  assert.equal(toHex(ecdsa.publicKey(key)), c['public_key']);
  assert.equal(toHex(ecdsa.sign(message, key)), c['signature']);
  assert.ok(ecdsa.verify(message, bytes(c['signature']), bytes(c['public_key'])));
});

eachCase('ecdsa.json', 'invalid', (c) => {
  assert.equal(
    ecdsa.verify(bytes(c['message_hex']), bytes(c['signature']), bytes(c['public_key'])),
    false,
  );
});

eachCase('vdf.json', 'valid', (c) => {
  const proof = vdf.evaluate(bytes(c['seed_hex']), c['t']);
  assert.equal(vdf.proofToHex(proof), c['proof']);
  assert.ok(vdf.verify(bytes(c['seed_hex']), c['t'], proof));
});

eachCase('vdf.json', 'invalid', (c) => {
  assert.equal(
    vdf.verify(bytes(c['seed_hex']), c['t'], vdf.hexToProof(c['proof'])),
    false,
  );
});

eachCase('vrf.json', 'valid', (c) => {
  const got = vrf.evaluate(bytes(c['message_hex']), bytes(c['secret_key']));
  assert.equal(toHex(got.publicKey), c['public_key']);
  assert.equal(toHex(got.proof), c['proof']);
  assert.equal(toHex(got.output), c['output']);
  assert.ok(vrf.verify(bytes(c['message_hex']), got.proof, got.publicKey, got.output));
});

eachCase('vrf.json', 'invalid', (c) => {
  assert.equal(
    vrf.verify(
      bytes(c['message_hex']),
      bytes(c['proof']),
      bytes(c['public_key']),
      bytes(c['output']),
    ),
    false,
  );
});

eachCase('discovery-peer.json', 'valid', (c) => {
  assert.equal(isValidAddress(c['address']), true);
});

eachCase('discovery-peer.json', 'invalid', (c) => {
  assert.equal(isValidAddress(c['address']), false);
});

eachCase('discovery-peer.json', 'sequence', (c, doc) => {
  const book = new AddressBook(c['listen'], c['capacity'], doc['default_timeout_ms']);
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    if (step['op'] === 'insert') {
      assert.equal(book.insert(step['address'], step['now_ms']), step['added'], where);
    } else if (step['op'] === 'ingest') {
      assert.equal(
        book.ingest(step['addresses'], step['now_ms'], step['solicited']),
        step['added'],
        where,
      );
    } else if (step['op'] === 'sweep') {
      assert.equal(book.sweep(step['now_ms']), step['expired'], where);
    } else if (step['op'] === 'advertise') {
      assert.deepEqual(book.advertise(), step['advertised'], where);
    } else {
      assert.fail(`unknown op ${step['op']}`);
    }
    assert.equal(book.size, step['size'], where);
    assert.deepEqual(book.addresses(), step['book'], where);
    assert.deepEqual(book.advertise(), step['advertised'], where);
  }
});

eachCase('discovery-local.json', 'sequence', (c) => {
  const book = new AddressBook(c['listen']);
  const local = new LocalDiscovery(book, c['enabled']);
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    if (step['op'] === 'insert') {
      assert.equal(book.insert(step['address'], step['now_ms']), step['added'], where);
    } else if (step['op'] === 'request') {
      assert.equal(local.request(step['peer']), step['ok'], where);
      assert.equal(book.isSolicited(step['peer']), step['solicited'], where);
    } else if (step['op'] === 'reply') {
      assert.deepEqual(local.reply(), step['peers'], where);
    } else if (step['op'] === 'accept') {
      assert.equal(
        local.accept(step['from'], step['addresses'], step['now_ms']),
        step['added'],
        where,
      );
      assert.equal(book.isSolicited(step['from']), step['solicited'], where);
    } else {
      assert.fail(`unknown op ${step['op']}`);
    }
    assert.equal(book.size, step['size'], where);
    assert.deepEqual(book.addresses(), step['book'], where);
    assert.deepEqual(book.advertise(), step['advertised'], where);
  }
});

eachCase('consensus-pow.json', 'replay', (c, doc) => {
  const obj = new ProofOfWork(doc['difficulty']);
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      blocks: step['blocks'],
      height: step['height'],
      tip: step['tip'],
    }, where);
  }
});

eachCase('consensus-pos.json', 'schedule', (c, doc) => {
  const obj = new ProofOfStake(doc['seed'], doc['validators']);
  assert.equal(obj.proposer(c['slot']), c['proposer']);
});

eachCase('consensus-pos.json', 'replay', (c) => {
  const obj = new ProofOfStake();
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      head: step['head'],
      last_proposer: step['last_proposer'],
      slot: step['slot'],
    }, where);
  }
});

eachCase('ledger-balance.json', 'replay', (c, doc) => {
  const obj = new BalanceLedger(doc['allocations']);
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      balances: step['balances'],
      burned: step['burned'],
      nonces: step['nonces'],
      supply: step['supply'],
    }, where);
  }
});

eachCase('ledger-utxo.json', 'replay', (c, doc) => {
  const obj = new UtxoLedger(doc['allocations']);
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      burned: step['burned'],
      supply: step['supply'],
      utxos: step['utxos'],
    }, where);
  }
});

eachCase('mempool-basic.json', 'sequence', (c) => {
  const pool = new Mempool(
    c['capacity'],
    c['min_fee'],
    c['ttl_ms'],
    c['max_per_sender'],
    c['rbf_min_increase'],
  );
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    const op = step['op'];
    if (op === 'insert') {
      const result = pool.insert(step['tx'], step['now_ms']);
      assert.equal(result.accepted, step['accepted'], where);
      assert.equal(result.replaced, step['replaced'], where);
      assert.equal(result.evicted, step['evicted'], where);
      assert.equal(result.expired, step['expired'], where);
    } else if (op === 'remove') {
      assert.equal(pool.remove(step['id']), step['removed'], where);
    } else if (op === 'sweep') {
      assert.equal(pool.sweep(step['now_ms']), step['expired'], where);
    } else {
      assert.fail(`unknown op ${op}`);
    }
    assert.deepEqual(pool.ids(), step['ids'], where);
    assert.equal(pool.size, step['size'], where);
  }
});

eachCase('fees-policy.json', 'select', (c) => {
  assert.deepEqual(fees.select(c['candidates'], c['limit']), c['ids']);
});

eachCase('fees-policy.json', 'charge', (c) => {
  assert.deepEqual(fees.charge(c['fee'], c['base']), {
    burned: c['burned'],
    charged: c['charged'],
    tip: c['tip'],
  });
});

eachCase('fees-policy.json', 'estimate', (c) => {
  assert.equal(fees.estimate(c['fees']), c['estimate']);
});

eachCase('fees-policy.json', 'base_fee', (c) => {
  assert.equal(fees.nextBaseFee(c['base'], c['parent_count'], c['target']), c['next']);
});

eachCase('consensus-pbft.json', 'replay', (c) => {
  const obj = new PBFT();
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      commits: step['commits'],
      executed: step['executed'],
      prepares: step['prepares'],
      sequence: step['sequence'],
      view: step['view'],
    }, where);
  }
});

// --- vector hygiene ---------------------------------------------------------

test('every vector file declares its feature', () => {
  const files = [
    'canonical-json.json',
    'digest.json',
    'envelope.json',
    'framing.json',
    'control.json',
    'signatures.json',
    'dedup.json',
    'memento.json',
    'pipeline.json',
    'ecdsa.json',
    'vdf.json',
    'vrf.json',
    'discovery-peer.json',
    'discovery-local.json',
    'consensus-pow.json',
    'consensus-pos.json',
    'consensus-pbft.json',
    'ledger-balance.json',
    'ledger-utxo.json',
    'mempool-basic.json',
    'fees-policy.json',
  ];
  for (const name of files) {
    const doc = load(name);
    for (const field of ['feature', 'spec', 'wire_version', 'generator']) {
      assert.ok(field in doc, `${name} is missing ${field}`);
    }
    assert.equal(doc['wire_version'], 1);
  }
});

test('vector files whose cases are parsed pin the clock', () => {
  // Without now_ms these tests would fall back to the wall clock and pass for
  // the wrong reason, until the fixed timestamps drifted out of range.
  for (const name of ['envelope.json', 'control.json', 'dedup.json']) {
    assert.equal(typeof load(name)['now_ms'], 'number', `${name} needs now_ms`);
  }
});
