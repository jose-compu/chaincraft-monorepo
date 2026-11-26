/**
 * Conformance vectors — the shared cross-language contract.
 *
 * Every implementation runs these same files. A failure here is a wire protocol
 * violation, not a local bug. Never edit a vector to make a test pass; see
 * AGENTS.md §7.
 */

import assert from 'node:assert/strict';
import type { JsonValue } from '../src/canonical.ts';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  AddressBook,
  CanonicalError,
  Avalanche,
  PBFT,
  ProofOfStake,
  ProofOfAuthority,
  Ouroboros,
  ProofOfTransfer,
  ProofOfElapsedTime,
  RandomnessBeacon,
  GENESIS_PREVIOUS,
  pulseId,
  ProofOfWork,
  BalanceLedger,
  CrdtKv,
  PubSub,
  Stream,
  UtxoLedger,
  Mempool,
  MessageStore,
  NodeSession,
  Swarm,
  NatTraversal,
  bindingRequest,
  bindingSuccess,
  parseBindingResponse,
  AdapterBus,
  AdapterChannel,
  LoopBus,
  LoopChannel,
  isChannelConnectAllowed,
  parseAddress,
  Deduplicator,
  fees,
  LocalDiscovery,
  Envelope,
  FrameReader,
  FramingError,
  ProtocolError,
  StateMemento,
  bytesToHex,
  canonicalJson,
  control,
  ecdsa,
  decodeDatagram,
  encodeDatagram,
  encodeFrame,
  frontierDigest,
  hexToBytes,
  BanSet,
  classifyInbound,
  isConnectAllowed,
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
  TransferChain,
  makeDriver,
  presetStart,
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

eachCase('discovery-peer.json', 'connect', (c) => {
  assert.equal(isConnectAllowed(c['address']), c['allowed']);
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

function banNowMs(step: Case, base: number): number | undefined {
  if (!('now_ms' in step)) return base;
  const raw = step['now_ms'];
  if (typeof raw === 'boolean') return undefined;
  if (typeof raw !== 'number' || raw < 0) return undefined;
  return raw;
}

function assertBanState(bs: BanSet, step: Case, base: number, where: string): void {
  const clock = banNowMs(step, base) ?? base;
  const state = bs.state(clock);
  assert.equal(state.size, step['size'], where);
  assert.deepEqual(state.banned, step['banned'], where);
  assert.deepEqual(state.tracked, step['tracked'], where);
}

eachCase('discovery-ban.json', 'sequence', (c, doc) => {
  const base = doc['now_ms'] as number;
  const bs = new BanSet(c['strike_limit'], c['ban_ttl_ms']);
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    if (step['op'] === 'note') {
      const nowMs = banNowMs(step, base);
      const result =
        nowMs === undefined
          ? 'ignored'
          : bs.note(String(step['peer']), String(step['reason']), nowMs);
      assert.equal(result, step['result'], where);
      if ('strikes' in step) {
        assert.equal(bs.strikes(String(step['peer'])), step['strikes'], where);
      }
    } else if (step['op'] === 'strikes') {
      assert.equal(bs.strikes(String(step['peer'])), step['strikes'], where);
    } else if (step['op'] === 'banned') {
      assert.deepEqual(bs.banned(banNowMs(step, base) ?? base), step['banned'], where);
    } else if (step['op'] === 'is_banned') {
      const peer = String(step['peer']);
      const nowMs = banNowMs(step, base);
      assert.equal(nowMs !== undefined, true, where);
      const expect = (step['banned'] as string[]).includes(peer);
      assert.equal(bs.isBanned(peer, nowMs!), expect, where);
    } else {
      assert.fail(`unknown op ${step['op']}`);
    }
    assertBanState(bs, step, base, where);
  }
  for (const [index, row] of (c['classify'] as Case[]).entries()) {
    const where = `classify ${index}`;
    const out = classifyInbound(
      String(row['type']),
      Boolean(row['solicited']),
      Boolean(row['duplicate']),
      Boolean(row['address_ok']),
    );
    assert.equal(out.action, row['action'], where);
    assert.equal(out.reason, row['reason'], where);
    assertBanState(bs, row, base, where);
  }
});

eachCase('consensus-ouroboros.json', 'replay', (c, doc) => {
  const nonce = doc['nonce'] as string;
  const epochLength = doc['epoch_length'] as number;
  const stakeholders = (doc['stakeholders'] as { id: string; stake: number; pk: string }[]).map(
    (entry) => ({ id: entry.id, stake: entry.stake, pk: entry.pk }),
  );
  const obj = new Ouroboros(nonce, epochLength, stakeholders);
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      slot: step['slot'],
      tip: step['tip'],
      canonical: step['canonical'],
      blocks: step['blocks'],
      epoch: step['epoch'],
      nonce: step['nonce'],
    }, where);
  }
  if (c['reorg_count'] !== undefined) {
    const steps = c['steps'] as Case[];
    const reorgs = steps.filter((step: Case) => step['reorg'] === true);
    assert.equal(reorgs.length, c['reorg_count']);
    const depths = reorgs.map((step: Case) => step['reorg_depth'] as number);
    assert.ok(Math.min(...depths) >= c['min_reorg_depth']);
  }
});

eachCase('consensus-poa.json', 'replay', (c, doc) => {
  const authorities = doc['authorities'] as string[];
  const obj = new ProofOfAuthority(authorities);
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      blocks: step['blocks'],
      canonical: step['canonical'],
      height: step['height'],
      tip: step['tip'],
    }, where);
  }
  if (c['reorg_count'] !== undefined) {
    const steps = c['steps'] as Case[];
    const reorgs = steps.filter((step: Case) => step['reorg']);
    assert.equal(reorgs.length, c['reorg_count']);
    const depths = reorgs.map((step: Case) => step['reorg_depth'] as number);
    assert.ok(Math.min(...depths) >= c['min_reorg_depth']);
  }
});

function parseReplayMessage(json: string): JsonValue | undefined {
  try {
    return parseJson(json);
  } catch (err) {
    if (err instanceof CanonicalError) return undefined;
    throw err;
  }
}

eachCase('consensus-pox.json', 'replay', (c, doc) => {
  const seed = doc['seed'] as string;
  const cycleLength = doc['cycle_length'] as number;
  const stackers = doc['stackers'] as { locker: string; amount: number }[];
  const obj = new ProofOfTransfer(seed, cycleLength, stackers);
  for (const [index, step] of c['steps'].entries()) {
    const message = parseReplayMessage(step['message_json']);
    const where = `step ${index}`;
    if (message === undefined) {
      assert.equal(step['accepted'], false, where);
      continue;
    }
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      height: step['height'],
      tip: step['tip'],
      open_height: step['open_height'],
      cycle: step['cycle'],
      canonical: step['canonical'],
      tenures: step['tenures'],
      bids: step['bids'],
      stacks: step['stacks'],
    }, where);
  }
});

eachCase('consensus-beacon.json', 'replay', (c) => {
  const obj = new RandomnessBeacon();
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      canonical: step['canonical'],
      height: step['height'],
      output: step['output'],
      pulses: step['pulses'],
    }, where);
  }
});

test('RandomnessBeacon constructor', () => {
  const empty = new RandomnessBeacon();
  assert.equal(
    empty.emitStateMemento().canonicalDigest,
    'b3d1cf3908c77c7645bf1bb5daf96e02d92038c62ffb771aec69d247f965f549',
  );
  const sk = hexToBytes('0000000000000000000000000000000000000000000000000000000000000003');
  const vrfMessage = new TextEncoder().encode(
    canonicalJson({ height: 0, previous: GENESIS_PREVIOUS }),
  );
  const { proof, output, publicKey } = vrf.evaluate(vrfMessage, sk);
  const pulse = {
    consensus: 'beacon',
    height: 0,
    previous: GENESIS_PREVIOUS,
    pk: bytesToHex(publicKey),
    proof: bytesToHex(proof),
    output: bytesToHex(output),
  };
  const doc = load('consensus-beacon.json');
  assert.equal(
    pulseId(pulse.height, pulse.output, pulse.pk, pulse.previous, pulse.proof),
    doc['genesis_id'],
  );
  const fresh = new RandomnessBeacon();
  assert.ok(fresh.isValid(pulse));
  fresh.addMessage(pulse);
  assert.equal(fresh.state().height, 0);
  assert.equal(fresh.state().output, pulse.output);
});

eachCase('consensus-poet.json', 'replay', (c, doc) => {
  const seed = doc['seed'] as string;
  const obj = new ProofOfElapsedTime(seed);
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.deepEqual(obj.state(), {
      canonical: step['canonical'],
      tickets: step['tickets'],
      wait: step['wait'],
      winner: step['winner'],
    }, where);
  }
});

test('ProofOfElapsedTime constructor', () => {
  assert.throws(() => new ProofOfElapsedTime(''));
  const empty = new ProofOfElapsedTime('poet-round');
  assert.equal(
    empty.emitStateMemento().canonicalDigest,
    'b937f65d3e33b1d2041b879a146f6ab092b2f1d3ff5a228ed1d9bf42268d357f',
  );
  const proof = vdf.proofToHex(vdf.evaluate(new TextEncoder().encode('poet-round'), 2));
  const msg = {
    author: 'alice',
    consensus: 'poet',
    payload: 'one',
    proof,
    wait: 2,
  };
  const fresh = new ProofOfElapsedTime('poet-round');
  assert.ok(fresh.isValid(msg));
  fresh.addMessage(msg);
  assert.equal(
    fresh.emitStateMemento().canonicalDigest,
    '671e91205e93cc18534c619c1caf6fdd469e1bdfbeb468dd65f43287c5315eb4',
  );
  const bobProof = vdf.proofToHex(vdf.evaluate(new TextEncoder().encode('poet-round'), 1));
  fresh.addMessage({
    author: 'bob',
    consensus: 'poet',
    payload: 'two',
    proof: bobProof,
    wait: 1,
  });
  assert.equal(
    fresh.emitStateMemento().canonicalDigest,
    'fd8a92143478eff67f0132fbc0fa293509ec06911fb41a0f61d1baffb7f84a04',
  );
});

test('ProofOfAuthority constructor', () => {
  assert.throws(() => new ProofOfAuthority([]));
  assert.throws(() => new ProofOfAuthority(['alice', 'alice']));
  assert.throws(() => new ProofOfAuthority(['alice', '']));
  const solo = new ProofOfAuthority(['solo']);
  const msg1 = { consensus: 'poa', height: 1, parent: '', payload: 'a', proposer: 'solo' };
  assert.ok(solo.isValid(msg1));
  solo.addMessage(msg1);
  const tip = solo.state().tip;
  const msg2 = { consensus: 'poa', height: 2, parent: tip, payload: 'b', proposer: 'solo' };
  assert.ok(solo.isValid(msg2));
  solo.addMessage(msg2);
  assert.equal(solo.state().height, 2);
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
      canonical: step['canonical'],
      height: step['height'],
      tip: step['tip'],
    }, where);
  }
  if (c['reorg_count'] !== undefined) {
    const steps = c['steps'] as Case[];
    const reorgs = steps.filter((step: Case) => step['reorg']);
    assert.equal(reorgs.length, c['reorg_count']);
    const depths = reorgs.map((step: Case) => step['reorg_depth'] as number);
    assert.ok(Math.min(...depths) >= c['min_reorg_depth']);
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

eachCase('app-pubsub.json', 'replay', (c) => {
  const obj = new PubSub();
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `${c['name']} step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) assert.equal(obj.addMessage(message), undefined, where);
    assert.equal(obj.isMerkelized(), false, where);
    assert.deepEqual(obj.getStateDigests(), [], where);
    const memo = obj.emitStateMemento();
    assert.equal(memo.canonicalDigest, '', where);
    assert.deepEqual(memo.frontierDigests, [], where);
    assert.deepEqual(obj.state(), { rooms: step['rooms'] }, where);
  }
});

eachCase('protocol-crdt-kv.json', 'replay', (c) => {
  const obj = new CrdtKv();
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `${c['name']} step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) assert.equal(obj.addMessage(message), undefined, where);
    assert.equal(obj.isMerkelized(), false, where);
    assert.deepEqual(obj.getStateDigests(), [], where);
    assert.deepEqual(obj.state(), { keys: step['keys'] }, where);
  }
});

eachCase('app-stream.json', 'replay', (c) => {
  const obj = new Stream();
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `${c['name']} step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) assert.equal(obj.addMessage(message), undefined, where);
    assert.equal(obj.isMerkelized(), false, where);
    assert.deepEqual(obj.getStateDigests(), [], where);
    const memo = obj.emitStateMemento();
    assert.equal(memo.canonicalDigest, '', where);
    assert.deepEqual(memo.frontierDigests, [], where);
    assert.deepEqual(obj.state(), { streams: step['streams'] }, where);
    const reads = step['reads'];
    if (Array.isArray(reads)) {
      for (const probe of reads) {
        assert.deepEqual(
          obj.read(probe['stream'], probe['partition'], probe['after'], probe['limit']),
          probe['events'],
          where,
        );
      }
    }
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

function jsonI64Map(value: unknown): Record<string, number> {
  const obj = value as Record<string, number>;
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(obj)) {
    out[k] = v;
  }
  return out;
}

function assertChainState(where: string, got: JsonValue, step: Case): void {
  const state = got as Record<string, JsonValue>;
  assert.deepEqual(jsonI64Map(state['balances']), jsonI64Map(step['balances']), `${where} balances`);
  assert.deepEqual(jsonI64Map(state['nonces']), jsonI64Map(step['nonces']), `${where} nonces`);
  assert.deepEqual(state['canonical'], step['canonical'], `${where} canonical`);
  assert.equal(state['height'], step['height'], `${where} height`);
  assert.equal(state['tip'], step['tip'], `${where} tip`);
}

test('chain-transfer.json replay', () => {
  const doc = load('chain-transfer.json');
  const genesis = jsonI64Map(doc['genesis']);
  for (const case_ of doc['replay'] as Case[]) {
    const name = String(case_['name']);
    const driver = makeDriver(String(case_['consensus']), case_['options'] as JsonValue);
    const chain = new TransferChain(genesis, case_['reward'] as number, driver);
    for (const [index, step] of (case_['steps'] as Case[]).entries()) {
      const where = `${name} step ${index}`;
      if (step['op'] === 'submit') {
        const message = parseJson(String(step['message_json']));
        const accepted = chain.submit(message);
        assert.equal(accepted, step['accepted'], where);
        assertChainState(where, chain.state(), step);
      } else if (step['op'] === 'produce') {
        const block = chain.produce(step['time'] as number, String(step['producer']));
        const accepted = block !== undefined;
        assert.equal(accepted, step['accepted'], where);
        assertChainState(where, chain.state(), step);
      } else if (step['op'] === 'accept_block') {
        const block = parseJson(String(step['block_json']));
        const accepted = chain.acceptBlock(block);
        assert.equal(accepted, step['accepted'], where);
        assertChainState(where, chain.state(), step);
      } else {
        assert.fail(`${where} unknown op ${String(step['op'])}`);
      }
    }
  }
});

test('node-preset.json', async () => {
  const doc = load('node-preset.json');
  const handle = await presetStart(doc['valid_config'] as JsonValue);
  assert.ok(
    handle.listenAddr.startsWith(String(doc['valid_listen_prefix'])),
    'listen addr',
  );
  const validConfig = doc['valid_config'] as Case;
  const authorities = { authorities: validConfig['authorities'] };
  const chain = new TransferChain(
    jsonI64Map(validConfig['genesis']),
    0,
    makeDriver(String(validConfig['consensus']), authorities as JsonValue),
  );
  const block = chain.produce(1, 'alice');
  assert.ok(block !== undefined, 'produce block');
  assert.equal(
    canonicalJson(block),
    canonicalJson(doc['hand_built_block'] as JsonValue),
    'hand-built block',
  );
  for (const item of doc['rejections'] as Case[]) {
    await assert.rejects(presetStart(item['config'] as JsonValue), (err: Error) => {
      assert.ok(err.message.includes(String(item['error'])), `expected ${item['error']} got ${err.message}`);
      return true;
    });
  }
  handle.close();
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

eachCase('storage-index.json', 'sequence', (c) => {
  const store = new MessageStore(c['capacity']);
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    const op = step['op'];
    if (op === 'register') {
      assert.equal(store.register(step['type'], step['field']), step['ok'], where);
    } else if (op === 'put') {
      assert.equal(store.put(step['id'], step['body']), step['added'], where);
    } else if (op === 'query') {
      assert.deepEqual(store.query(step['type'], step['field'], step['value']), step['hits'], where);
    } else if (op === 'remove') {
      assert.equal(store.remove(step['id']), step['removed'], where);
    } else if (op === 'load') {
      assert.equal(store.load(step['snapshot']), step['ok'], where);
    } else {
      assert.fail(`unknown op ${op}`);
    }
    assert.deepEqual(store.ids(), step['ids'], where);
    assert.equal(store.size, step['size'], where);
    assert.deepEqual(store.dump(), step['dump'], where);
  }
});

eachCase('storage-persistent.json', 'sequence', (c) => {
  const store = new MessageStore(c['capacity']);
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    const op = step['op'];
    if (op === 'put') {
      assert.equal(store.put(step['id'], step['body']), step['added'], where);
    } else if (op === 'get') {
      assert.deepEqual(store.get(step['id']), { body: step['body'], found: step['found'] }, where);
    } else if (op === 'remove') {
      assert.equal(store.remove(step['id']), step['removed'], where);
    } else if (op === 'load') {
      assert.equal(store.load(step['snapshot']), step['ok'], where);
    } else {
      assert.fail(`unknown op ${op}`);
    }
    assert.deepEqual(store.ids(), step['ids'], where);
    assert.equal(store.size, step['size'], where);
    assert.deepEqual(store.dump(), step['dump'], where);
  }
});

eachCase('cli-node.json', 'sequence', (c) => {
  const session = new NodeSession(c['impl'], c['listen']);
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    const events = step['op'] === 'start' ? session.start() : session.handle(step['line']);
    assert.deepEqual(events, step['events'], where);
    assert.deepEqual(session.state(), {
      closed: step['closed'],
      ids: step['ids'],
      peers: step['peers'],
    }, where);
  }
});

eachCase('wire-channel.json', 'parse', (c) => {
  assert.deepEqual(parseAddress(c['input']), {
    ok: c['ok'],
    scheme: c['scheme'],
    canonical: c['canonical'],
    cap: c['cap'],
  });
});

eachCase('wire-channel.json', 'connect', (c) => {
  assert.equal(isChannelConnectAllowed(c['input']), c['allowed']);
});

eachCase('wire-channel.json', 'sequence', (c) => {
  const bus = new LoopBus();
  const peers = { a: new LoopChannel(bus), b: new LoopChannel(bus) };
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    const actor = peers[step['who'] as 'a' | 'b'];
    const op = step['op'];
    if (op === 'listen') {
      assert.equal(actor.listen(step['addr']), step['ok'], where);
    } else if (op === 'dial') {
      assert.equal(actor.dial(step['addr']), step['ok'], where);
    } else if (op === 'send') {
      assert.equal(actor.send(step['addr'], step['data']), step['ok'], where);
    } else if (op === 'recv') {
      assert.deepEqual(actor.recv(), step['returned'], where);
    } else if (op === 'close') {
      actor.close();
    } else {
      assert.fail(`unknown op ${op}`);
    }
    assert.equal(peers.a.listenAddr, step['a_listen'], where);
    assert.equal(peers.b.listenAddr, step['b_listen'], where);
    assert.deepEqual(peers.a.inbox(), step['a_inbox'], where);
    assert.deepEqual(peers.b.inbox(), step['b_inbox'], where);
  }
});

eachCase('channel-adapters.json', 'sequence', (c) => {
  const factories = {
    udp: () => AdapterBus.udp(),
    mailto: () => AdapterBus.mail(),
    webrtc: () => AdapterBus.webrtc(),
    forum: () => AdapterBus.forum(),
    pipe: () => AdapterBus.pipe(),
  };
  const bus = factories[c['scheme'] as keyof typeof factories]();
  const peers = { a: new AdapterChannel(bus), b: new AdapterChannel(bus) };
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    const actor = peers[step['who'] as 'a' | 'b'];
    const op = step['op'];
    if (op === 'listen') assert.equal(actor.listen(step['addr']), step['ok'], where);
    else if (op === 'dial') assert.equal(actor.dial(step['addr']), step['ok'], where);
    else if (op === 'send') assert.equal(actor.send(step['addr'], step['data']), step['ok'], where);
    else if (op === 'recv') assert.deepEqual(actor.recv(), step['returned'], where);
    else if (op === 'close') actor.close();
    else assert.fail(`unknown op ${op}`);
    assert.equal(peers.a.listenAddr, step['a_listen'], where);
    assert.equal(peers.b.listenAddr, step['b_listen'], where);
    assert.deepEqual(peers.a.inbox(), step['a_inbox'], where);
    assert.deepEqual(peers.b.inbox(), step['b_inbox'], where);
  }
});

eachCase('bittorrent-swarm.json', 'replay', (c) => {
  const obj = new Swarm();
  const digest = c['info_hash'];
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index}`;
    const accepted = obj.isValid(step['message']);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) assert.equal(obj.addMessage(step['message']), undefined, where);
    assert.equal(obj.isMerkelized(), false, where);
    const memo = obj.emitStateMemento();
    assert.equal(memo.canonicalDigest, '', where);
    assert.deepEqual(memo.frontierDigests, [], where);
    assert.equal(obj.assembled(digest), step['assembled'], where);
    assert.deepEqual(obj.state(), step['state'], where);
  }
});

eachCase('consensus-avalanche.json', 'replay', (c) => {
  const obj = new Avalanche(c['steps'][0]['phase']);
  for (const [index, step] of c['steps'].entries()) {
    const message = parseJson(step['message_json']);
    const where = `${c['name']} step ${index}`;
    const accepted = obj.isValid(message);
    assert.equal(accepted, step['accepted'], where);
    if (accepted) obj.addMessage(message);
    assert.equal(obj.isMerkelized(), true, where);
    assert.deepEqual(obj.state(), {
      cnt: step['cnt'],
      d: step['d'],
      final: step['final'],
      phase: step['phase'],
      pref: step['pref'],
      rounds: step['rounds'],
    }, where);
  }
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

// --- Level 2 NAT ------------------------------------------------------------

eachCase('discovery-nat.json', 'request', (c) => {
  assert.deepEqual(bindingRequest(c['txid']), { ok: c['ok'], packet: c['packet'] });
});

eachCase('discovery-nat.json', 'success', (c) => {
  assert.deepEqual(bindingSuccess(c['txid'], c['host'], c['port']), {
    ok: c['ok'],
    packet: c['packet'],
  });
});

eachCase('discovery-nat.json', 'response', (c) => {
  assert.deepEqual(parseBindingResponse(c['packet'], c['txid']), {
    ok: c['ok'],
    host: c['host'],
    port: c['port'],
  });
});

eachCase('discovery-nat.json', 'construct', (c) => {
  if (!c['ok']) {
    assert.throws(
      () => new NatTraversal(c['listen'], c['external'], c['relay']),
      ProtocolError,
    );
    return;
  }
  const node = new NatTraversal(c['listen'], c['external'], c['relay']);
  assert.equal(node.advertise(), c['advertise']);
});

eachCase('discovery-nat.json', 'sequence', (c) => {
  const node = new NatTraversal(c['listen'], c['external'], c['relay']);
  for (const [index, step] of c['steps'].entries()) {
    const where = `step ${index} (${step['op']})`;
    const op = step['op'];
    if (op === 'arm') {
      assert.equal(node.arm(step['transport']), step['ok'], where);
    } else if (op === 'observe_stun') {
      assert.equal(node.observeStun(step['packet'], step['txid']), step['ok'], where);
    } else if (op === 'punch') {
      assert.deepEqual(node.punch(step['peer']), {
        ok: step['ok'],
        datagram: step['datagram'],
        addr: step['addr'],
      }, where);
    } else if (op === 'observe_punch') {
      assert.equal(node.observePunch(step['datagram'], step['from']), step['ok'], where);
    } else if (op === 'relay_request') {
      assert.deepEqual(node.relayRequest(step['target']), {
        ok: step['ok'],
        message: step['message'],
      }, where);
    } else if (op === 'handle') {
      assert.deepEqual(node.handle(step['message']), {
        ok: step['ok'],
        action: step['action'],
        addr: step['addr'],
        reply: step['reply'],
      }, where);
    } else {
      throw new Error(`unknown op ${op}`);
    }
    assert.equal(node.advertise(), step['advertise'], where);
    assert.equal(node.armed(), step['armed'], where);
    assert.equal(node.externalAddress(), step['external'], where);
    assert.deepEqual(node.opened(), step['opened'], where);
  }
});

eachCase('wire-paths.json', 'classify', (c) => {
  const env = Envelope.build(c['type'], { n: 1 }, { ts: c['ts'] });
  assert.equal(env.path(), c['path']);
  assert.equal(env.isControl(), c['path'] === 'control');
  const dedup = new Deduplicator();
  assert.equal(dedup.shouldProcess(env), c['first_process']);
  assert.equal(dedup.shouldProcess(env), c['repeat_process']);
  assert.equal(dedup.shouldRelay(env), c['relay']);
  assert.equal(dedup.seen.size, c['seen_size']);
});

// --- vector hygiene ---------------------------------------------------------

test('channel.peer transcript', async () => {
  const { EnvelopeRelay, DEFAULT_PEER_ORIGIN, parsePeerIdBody, peerOptions } = await import(
    '../src/peer.ts'
  );
  const doc = load('channel-peer.json');
  assert.equal(doc['origin'], DEFAULT_PEER_ORIGIN);
  assert.deepEqual(peerOptions(), doc['options']);
  for (const item of doc['ids'] as Array<{ name: string; input: string; id: string | null }>) {
    assert.equal(parsePeerIdBody(item.input), item.id ?? undefined, item.name);
  }
  const relay = new EnvelopeRelay();
  for (const step of doc['steps'] as Array<Record<string, unknown>>) {
    if (step['op'] === 'join') {
      assert.equal(relay.join(String(step['addr'])), step['ok'], String(step['addr']));
    } else if (step['op'] === 'publish') {
      assert.equal(
        relay.publish(String(step['src']), String(step['type']), JSON.parse(String(step['data']))),
        step['id'] ?? undefined,
        String(step['src']),
      );
    } else if (step['op'] === 'take') {
      assert.deepEqual(relay.take(String(step['addr'])), step['inbox'], String(step['addr']));
    } else {
      assert.fail(String(step['op']));
    }
  }
});

test('channel.hybrid transcript', async () => {
  const { LinkMesh, helloCaps } = await import('../src/hybrid.ts');
  const doc = load('channel-hybrid.json');
  assert.deepEqual(helloCaps(false), doc['caps_tcp']);
  assert.deepEqual(helloCaps(true), doc['caps_udp']);
  const mesh = new LinkMesh();
  for (const step of doc['steps'] as Array<Record<string, unknown>>) {
    if (step['op'] === 'join') {
      assert.equal(mesh.join(String(step['addr'])), step['ok'], String(step['addr']));
    } else if (step['op'] === 'gossip') {
      assert.equal(
        mesh.gossip(String(step['src']), String(step['type']), JSON.parse(String(step['data']))),
        step['id'] ?? undefined,
        String(step['src']),
      );
    } else if (step['op'] === 'direct') {
      assert.equal(
        mesh.direct(
          String(step['src']),
          String(step['dst']),
          String(step['type']),
          JSON.parse(String(step['data'])),
        ),
        step['id'] ?? undefined,
        String(step['dst']),
      );
    } else if (step['op'] === 'take') {
      assert.deepEqual(mesh.take(String(step['addr'])), step['inbox'], String(step['addr']));
    } else {
      assert.fail(String(step['op']));
    }
  }
});

test('every vector file declares its feature', () => {
  const files = [
    'canonical-json.json',
    'digest.json',
    'envelope.json',
    'framing.json',
    'control.json',
    'signatures.json',
    'dedup.json',
    'wire-paths.json',
    'memento.json',
    'pipeline.json',
    'ecdsa.json',
    'vdf.json',
    'vrf.json',
    'discovery-peer.json',
    'discovery-ban.json',
    'discovery-local.json',
    'consensus-ouroboros.json',
    'consensus-poa.json',
    'consensus-poet.json',
    'consensus-pox.json',
    'consensus-beacon.json',
    'consensus-pow.json',
    'consensus-pos.json',
    'consensus-pbft.json',
    'consensus-avalanche.json',
    'ledger-balance.json',
    'ledger-utxo.json',
    'mempool-basic.json',
    'fees-policy.json',
    'storage-persistent.json',
    'storage-index.json',
    'cli-node.json',
    'bittorrent-swarm.json',
    'discovery-nat.json',
    'wire-channel.json',
    'channel-adapters.json',
    'channel-peer.json',
    'channel-hybrid.json',
    'app-pubsub.json',
    'app-stream.json',
    'protocol-crdt-kv.json',
    'chain-transfer.json',
    'node-preset.json',
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
