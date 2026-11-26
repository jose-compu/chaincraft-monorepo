/** Consensus drivers for chain.transfer — SPEC/features/chain-transfer.md. */

import type { JsonValue } from './canonical.ts';
import { canonicalJson, bytesToHex, hexToBytes } from './canonical.ts';
import { blockId, type ChainDriver } from './chain.ts';
import { Avalanche } from './consensusAvalanche.ts';
import { RandomnessBeacon, GENESIS_PREVIOUS } from './consensusBeacon.ts';
import { Ouroboros, blockId as ouroborosBlockId } from './consensusOuroboros.ts';
import { PBFT } from './consensusPbft.ts';
import { ProofOfAuthority, blockId as poaBlockId, proposerFor as poaProposerFor } from './consensusPoa.ts';
import { ProofOfElapsedTime } from './consensusPoet.ts';
import { ProofOfStake, proposerFor as posProposerFor } from './consensusPos.ts';
import { ProofOfWork, blockId as powBlockId, meetsWork } from './consensusPow.ts';
import { ProofOfTransfer, sortitionScore } from './consensusPox.ts';
import { merkleDigest } from './object.ts';
import * as vdf from './vdf.ts';
import * as vrf from './vrf.ts';

function asRecord(value: JsonValue): Record<string, JsonValue> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, JsonValue>;
}

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function headerFromBlock(block: JsonValue): Record<string, JsonValue> {
  const obj = asRecord(block);
  if (obj === undefined) throw new Error('header required');
  const raw = obj['header'];
  if (raw === undefined) throw new Error('header required');
  const header = asRecord(raw);
  if (header === undefined) throw new Error('header required');
  return header;
}

function headerFromBlockOpt(block: JsonValue): Record<string, JsonValue> | undefined {
  const obj = asRecord(block);
  if (obj === undefined) return undefined;
  const raw = obj['header'];
  if (raw === undefined) return undefined;
  return asRecord(raw);
}

class BaseDriver {
  private readonly chainToConsensus = new Map<string, string>();
  private readonly consensusToChain = new Map<string, string>();

  remember(chainId: string, consensusId: string): void {
    this.chainToConsensus.set(chainId, consensusId);
    this.consensusToChain.set(consensusId, chainId);
  }

  powParent(chainParent: string): string {
    if (chainParent === '') return '';
    return this.chainToConsensus.get(chainParent) ?? '';
  }

  canonicalPayloads(consensusCanon: readonly string[]): string[] {
    const out: string[] = [];
    for (const id of consensusCanon) {
      const mapped = this.consensusToChain.get(id);
      if (mapped !== undefined) out.push(mapped);
    }
    return out;
  }
}

export function makeDriver(consensus: string, options: JsonValue): ChainDriver {
  const name = consensus.toLowerCase();
  const opts = asRecord(options) ?? {};
  switch (name) {
    case 'pow': {
      const difficulty = isInt(opts['difficulty']) ? opts['difficulty'] : 1;
      return new PowDriver(difficulty);
    }
    case 'poa': {
      const authorities = stringList(opts['authorities']) ?? ['alice'];
      return new PoaDriver(authorities);
    }
    case 'pos':
      return new PosDriver();
    case 'pbft':
      return new PbftDriver(opts['replicas']);
    case 'poet': {
      const seed =
        typeof opts['seed'] === 'string' ? opts['seed'] : 'chaincraft-poet-genesis';
      return new PoetDriver(seed);
    }
    case 'avalanche':
      return new AvalancheDriver();
    case 'beacon': {
      const beaconName = typeof opts['name'] === 'string' ? opts['name'] : 'alice';
      const skHex = typeof opts['sk'] === 'string' ? opts['sk'] : undefined;
      const sk = skHex === undefined ? undefined : hexToBytes(skHex);
      return new BeaconDriver(beaconName, sk);
    }
    case 'pox':
      return new PoxDriver();
    case 'ouroboros':
      return new OuroborosDriver();
    default:
      throw new Error(`unknown consensus: ${consensus}`);
  }
}

function stringList(value: JsonValue | undefined): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const out: string[] = [];
  for (const item of value) {
    if (typeof item !== 'string') return undefined;
    out.push(item);
  }
  return out;
}

class PowDriver implements ChainDriver {
  private readonly base = new BaseDriver();
  private readonly pow: ProofOfWork;

  constructor(difficulty: number) {
    this.pow = new ProofOfWork(difficulty);
  }

  buildProof(block: JsonValue): JsonValue {
    const header = headerFromBlock(block);
    const cid = blockId(header);
    const parent = this.base.powParent(String(header['parent'] ?? ''));
    const height = header['height'];
    const producer = header['producer'];
    if (!isInt(height) || typeof producer !== 'string') throw new Error('header');
    let nonce = 0;
    const difficulty = this.pow.difficulty;
    while (true) {
      const digest = powBlockId(height, producer, nonce, parent, cid);
      if (meetsWork(digest, difficulty)) {
        return {
          consensus: 'pow',
          height,
          miner: producer,
          nonce,
          parent,
          payload: cid,
          id: digest,
        };
      }
      nonce += 1;
    }
  }

  authorize(block: JsonValue, proof: JsonValue): boolean {
    const obj = asRecord(proof);
    if (obj === undefined || obj['consensus'] !== 'pow') return false;
    const header = headerFromBlockOpt(block);
    if (header === undefined) return false;
    let cid: string;
    try {
      cid = blockId(header);
    } catch {
      return false;
    }
    if (obj['payload'] !== cid) return false;
    if (!this.pow.isValid(proof)) return false;
    this.pow.addMessage(proof);
    const consensusId = obj['id'];
    if (typeof consensusId !== 'string') return false;
    this.base.remember(cid, consensusId);
    return true;
  }

  canonical(): string[] {
    const { canonical } = this.pow.state();
    return this.base.canonicalPayloads(canonical);
  }
}

class PoaDriver implements ChainDriver {
  private readonly base = new BaseDriver();
  private readonly authorities: string[];
  private readonly poa: ProofOfAuthority;

  constructor(authorities: string[]) {
    this.authorities = authorities;
    this.poa = new ProofOfAuthority(authorities);
  }

  buildProof(block: JsonValue): JsonValue {
    const header = headerFromBlock(block);
    const cid = blockId(header);
    const parent = this.base.powParent(String(header['parent'] ?? ''));
    const height = header['height'];
    const proposer = header['producer'];
    if (!isInt(height) || typeof proposer !== 'string') throw new Error('header');
    return {
      consensus: 'poa',
      height,
      parent,
      payload: cid,
      proposer,
    };
  }

  authorize(block: JsonValue, proof: JsonValue): boolean {
    const obj = asRecord(proof);
    if (obj === undefined || obj['consensus'] !== 'poa') return false;
    const header = headerFromBlockOpt(block);
    if (header === undefined) return false;
    let cid: string;
    try {
      cid = blockId(header);
    } catch {
      return false;
    }
    if (obj['payload'] !== cid) return false;
    const height = header['height'];
    if (!isInt(height)) return false;
    if (obj['proposer'] !== poaProposerFor(height, this.authorities)) return false;
    if (!this.poa.isValid(proof)) return false;
    this.poa.addMessage(proof);
    const h = obj['height'];
    const p = obj['parent'];
    const payload = obj['payload'];
    const proposer = obj['proposer'];
    if (!isInt(h) || typeof p !== 'string' || typeof payload !== 'string' || typeof proposer !== 'string') {
      return false;
    }
    const digest = poaBlockId(h, p, payload, proposer);
    this.base.remember(cid, digest);
    return true;
  }

  canonical(): string[] {
    const { canonical } = this.poa.state();
    return this.base.canonicalPayloads(canonical);
  }
}

class PosDriver implements ChainDriver {
  private readonly pos = new ProofOfStake();
  private readonly chainIds: string[] = [];

  buildProof(block: JsonValue): JsonValue {
    const header = headerFromBlock(block);
    const cid = blockId(header);
    const slot = header['height'];
    if (!isInt(slot)) throw new Error('header');
    const proposer = posProposerFor(slot, this.pos.seed, this.pos.validators);
    return { consensus: 'pos', payload: cid, proposer, slot };
  }

  authorize(block: JsonValue, proof: JsonValue): boolean {
    const obj = asRecord(proof);
    if (obj === undefined || obj['consensus'] !== 'pos') return false;
    const header = headerFromBlockOpt(block);
    if (header === undefined) return false;
    if (header['time'] !== header['height']) return false;
    let cid: string;
    try {
      cid = blockId(header);
    } catch {
      return false;
    }
    if (obj['payload'] !== cid) return false;
    if (!this.pos.isValid(proof)) return false;
    this.pos.addMessage(proof);
    this.chainIds.push(cid);
    return true;
  }

  canonical(): string[] {
    return [...this.chainIds];
  }
}

class PbftDriver implements ChainDriver {
  private readonly pbft: PBFT;
  private readonly executed: string[] = [];

  constructor(replicas: JsonValue | undefined) {
    const list = stringList(replicas);
    this.pbft = list === undefined ? new PBFT() : new PBFT(list);
  }

  buildProof(block: JsonValue): JsonValue {
    const header = headerFromBlock(block);
    const cid = blockId(header);
    const primary = this.pbft.primaryFor(0);
    const prepares = [...this.pbft.replicas].sort().slice(0, this.pbft.quorum);
    const commits = [...prepares];
    const digest = merkleDigest(cid);
    return {
      consensus: 'pbft',
      value: cid,
      digest,
      primary,
      prepares,
      commits,
    };
  }

  authorize(block: JsonValue, proof: JsonValue): boolean {
    const obj = asRecord(proof);
    if (obj === undefined || obj['consensus'] !== 'pbft') return false;
    const header = headerFromBlockOpt(block);
    if (header === undefined) return false;
    let cid: string;
    try {
      cid = blockId(header);
    } catch {
      return false;
    }
    if (obj['value'] !== cid) return false;
    const digest = obj['digest'];
    if (typeof digest !== 'string' || merkleDigest(cid) !== digest) return false;
    const primary = this.pbft.primaryFor(0);
    const seq = this.pbft.sequence;
    const msgs: JsonValue[] = [
      {
        consensus: 'pbft',
        phase: 'pre-prepare',
        view: 0,
        sequence: seq,
        digest,
        replica: primary,
        value: cid,
      },
    ];
    const prepares = obj['prepares'];
    if (Array.isArray(prepares)) {
      for (const rep of prepares) {
        if (typeof rep !== 'string') return false;
        msgs.push({
          consensus: 'pbft',
          phase: 'prepare',
          view: 0,
          sequence: seq,
          digest,
          replica: rep,
        });
      }
    }
    const commits = obj['commits'];
    if (Array.isArray(commits)) {
      for (const rep of commits) {
        if (typeof rep !== 'string') return false;
        msgs.push({
          consensus: 'pbft',
          phase: 'commit',
          view: 0,
          sequence: seq,
          digest,
          replica: rep,
        });
      }
    }
    for (const msg of msgs) {
      if (!this.pbft.isValid(msg)) return false;
      this.pbft.addMessage(msg);
    }
    this.executed.push(cid);
    return true;
  }

  canonical(): string[] {
    return [...this.executed];
  }
}

class PoetDriver implements ChainDriver {
  private readonly heightSeed: string;
  private readonly perHeight = new Map<number, ProofOfElapsedTime>();
  private readonly canonicalIds: string[] = [];

  constructor(seed: string) {
    this.heightSeed = seed;
  }

  private poetFor(header: Record<string, JsonValue>): ProofOfElapsedTime {
    const height = header['height'];
    if (!isInt(height)) throw new Error('height');
    let poet = this.perHeight.get(height);
    if (poet === undefined) {
      const seed = height === 1 ? this.heightSeed : String(header['parent'] ?? '');
      poet = new ProofOfElapsedTime(seed);
      this.perHeight.set(height, poet);
    }
    return poet;
  }

  buildProof(block: JsonValue): JsonValue {
    const header = headerFromBlock(block);
    const cid = blockId(header);
    this.poetFor(header);
    const wait = 1;
    const h = header['height'];
    if (!isInt(h)) throw new Error('height');
    const seedStr = h === 1 ? this.heightSeed : String(header['parent'] ?? '');
    const seedRaw = new TextEncoder().encode(seedStr);
    const proofInt = vdf.evaluate(seedRaw, wait);
    const proofHex = vdf.proofToHex(proofInt);
    const producer = header['producer'];
    if (typeof producer !== 'string') throw new Error('header');
    return {
      consensus: 'poet',
      author: producer,
      payload: cid,
      wait,
      proof: proofHex,
    };
  }

  authorize(block: JsonValue, proof: JsonValue): boolean {
    const obj = asRecord(proof);
    if (obj === undefined || obj['consensus'] !== 'poet') return false;
    const header = headerFromBlockOpt(block);
    if (header === undefined) return false;
    let cid: string;
    try {
      cid = blockId(header);
    } catch {
      return false;
    }
    if (obj['payload'] !== cid) return false;
    const poet = this.poetFor(header);
    if (!poet.isValid(proof)) return false;
    poet.addMessage(proof);
    if (!this.canonicalIds.includes(cid)) this.canonicalIds.push(cid);
    return true;
  }

  canonical(): string[] {
    return [...this.canonicalIds];
  }
}

class AvalancheDriver implements ChainDriver {
  private readonly perHeight = new Map<number, Avalanche>();
  private readonly canonicalIds: string[] = [];

  private snow(height: number): Avalanche {
    let snow = this.perHeight.get(height);
    if (snow === undefined) {
      snow = new Avalanche('snowball', 1, 1, 1);
      this.perHeight.set(height, snow);
    }
    return snow;
  }

  buildProof(_block: JsonValue): JsonValue {
    return {
      consensus: 'avalanche',
      messages: [
        { color: 'blue', consensus: 'avalanche', op: 'init' },
        { consensus: 'avalanche', op: 'round', votes: ['blue'] },
      ],
    };
  }

  authorize(block: JsonValue, proof: JsonValue): boolean {
    const obj = asRecord(proof);
    if (obj === undefined || obj['consensus'] !== 'avalanche') return false;
    const header = headerFromBlockOpt(block);
    if (header === undefined) return false;
    const height = header['height'];
    if (!isInt(height)) return false;
    const snow = this.snow(height);
    const messages = obj['messages'];
    if (Array.isArray(messages)) {
      for (const msg of messages) {
        if (!snow.isValid(msg)) return false;
        snow.addMessage(msg);
      }
    }
    if (!snow.state().final) return false;
    let cid: string;
    try {
      cid = blockId(header);
    } catch {
      return false;
    }
    if (!this.canonicalIds.includes(cid)) this.canonicalIds.push(cid);
    return true;
  }

  canonical(): string[] {
    return [...this.canonicalIds];
  }
}

class BeaconDriver implements ChainDriver {
  private readonly name: string;
  private readonly sk: Uint8Array | undefined;
  private readonly pkHex: string;
  private readonly beacon = new RandomnessBeacon();
  private readonly canonicalIds: string[] = [];

  constructor(name: string, sk: Uint8Array | undefined) {
    this.name = name;
    this.sk = sk;
    let pkHex = '';
    if (sk !== undefined) {
      const result = vrf.evaluate(new TextEncoder().encode('bootstrap'), sk);
      pkHex = bytesToHex(result.publicKey);
    }
    this.pkHex = pkHex;
  }

  private pulseMessage(height: number, previous: string): Uint8Array {
    return new TextEncoder().encode(canonicalJson({ height, previous }));
  }

  private previousOutput(): string {
    const { height, output } = this.beacon.state();
    if (height < 0) return GENESIS_PREVIOUS;
    return output;
  }

  buildProof(block: JsonValue): JsonValue {
    const header = headerFromBlock(block);
    const beaconHeight = (header['height'] as number) - 1;
    const previous = this.previousOutput();
    if (this.sk === undefined) throw new Error('beacon driver requires sk');
    const message = this.pulseMessage(beaconHeight, previous);
    const result = vrf.evaluate(message, this.sk);
    return {
      consensus: 'beacon',
      height: beaconHeight,
      previous,
      pk: bytesToHex(result.publicKey),
      proof: bytesToHex(result.proof),
      output: bytesToHex(result.output),
    };
  }

  authorize(block: JsonValue, proof: JsonValue): boolean {
    const obj = asRecord(proof);
    if (obj === undefined || obj['consensus'] !== 'beacon') return false;
    const header = headerFromBlockOpt(block);
    if (header === undefined) return false;
    if (header['producer'] !== this.name) return false;
    if (obj['pk'] !== this.pkHex) return false;
    const expectedH = (header['height'] as number) - 1;
    if (obj['height'] !== expectedH) return false;
    if (!this.beacon.isValid(proof)) return false;
    this.beacon.addMessage(proof);
    try {
      this.canonicalIds.push(blockId(header));
    } catch {
      return false;
    }
    return true;
  }

  canonical(): string[] {
    return [...this.canonicalIds];
  }
}

export const POX_SEED = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
export const POX_CYCLE = 3;
export const OURO_NONCE =
  '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
export const OURO_EPOCH = 2;

export function ouroTable(): { id: string; stake: number; pk: string }[] {
  const aliceSk = new Uint8Array([...new Uint8Array(31), 3]);
  const bobSk = hexToBytes(
    'c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721',
  );
  const rows: { id: string; stake: number; pk: string }[] = [];
  for (const [sid, stake, sk] of [
    ['alice', 100, aliceSk] as const,
    ['bob', 1, bobSk] as const,
  ]) {
    const pk = vrf.evaluate(new TextEncoder().encode('bootstrap'), sk).publicKey;
    rows.push({ id: sid, stake, pk: bytesToHex(pk) });
  }
  return rows;
}

function ouroKeys(): Map<string, Uint8Array> {
  return new Map([
    ['alice', new Uint8Array([...new Uint8Array(31), 3])],
    [
      'bob',
      hexToBytes('c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721'),
    ],
  ]);
}

type PoxInternals = {
  electedMiner(h: number): string | undefined;
  tip(): { id: string; height: number };
};

class PoxDriver implements ChainDriver {
  private readonly pox = new ProofOfTransfer(
    POX_SEED,
    POX_CYCLE,
    [
      { locker: 'alice', amount: 100 },
      { locker: 'bob', amount: 200 },
      { locker: 'carol', amount: 50 },
    ],
  );
  private readonly chainIds: string[] = [];

  private poxElected(height: number): string {
    const miners: [string, number][] = [
      ['alice', 5],
      ['bob', 6],
      ['carol', 4],
    ];
    let bestMiner = 'alice';
    let bestScore = '';
    for (const [miner, btc] of miners) {
      const score = sortitionScore(POX_SEED, miner, btc, height);
      if (!bestScore || score < bestScore) {
        bestMiner = miner;
        bestScore = score;
      }
    }
    return bestMiner;
  }

  buildProof(block: JsonValue): JsonValue {
    const header = headerFromBlock(block);
    const h = header['height'];
    if (!isInt(h)) throw new Error('header');
    const elected = this.poxElected(h);
    const tipId = this.pox.state().tip;
    const prev = h === 1 ? '' : tipId;
    const bids: JsonValue[] = [
      { consensus: 'pox', kind: 'bid', miner: 'alice', btc_out: 5, block_height: h },
      { consensus: 'pox', kind: 'bid', miner: 'bob', btc_out: 6, block_height: h },
      { consensus: 'pox', kind: 'bid', miner: 'carol', btc_out: 4, block_height: h },
    ];
    const tenure = {
      consensus: 'pox',
      kind: 'tenure',
      winner: elected,
      prev,
      block_height: h,
    };
    return { consensus: 'pox', messages: [...bids, tenure] };
  }

  authorize(block: JsonValue, proof: JsonValue): boolean {
    const obj = asRecord(proof);
    if (obj === undefined || obj['consensus'] !== 'pox') return false;
    const header = headerFromBlockOpt(block);
    if (header === undefined) return false;
    const height = header['height'];
  if (!isInt(height)) return false;
    const messages = obj['messages'];
    if (!Array.isArray(messages)) return false;
    const bids: JsonValue[] = [];
    const tenures: JsonValue[] = [];
    for (const msg of messages) {
      const rec = asRecord(msg);
      if (rec?.['kind'] === 'bid') bids.push(msg);
      else if (rec?.['kind'] === 'tenure') tenures.push(msg);
      else return false;
    }
    for (const msg of bids) {
      if (!this.pox.isValid(msg)) return false;
      this.pox.addMessage(msg);
    }
    const elected = (this.pox as unknown as PoxInternals).electedMiner(height);
    if (elected === undefined || header['producer'] !== elected) return false;
    for (const msg of tenures) {
      if (!this.pox.isValid(msg)) return false;
      this.pox.addMessage(msg);
    }
    try {
      if (header !== undefined) this.chainIds.push(blockId(header));
    } catch {
      return false;
    }
    return true;
  }

  canonical(): string[] {
    return [...this.chainIds];
  }
}

class OuroborosDriver implements ChainDriver {
  private readonly ouro: Ouroboros;
  private readonly chainToOuro = new Map<string, string>();
  private readonly ouroMessages = new Map<string, JsonValue>();

  constructor() {
    const table = ouroTable();
    this.ouro = new Ouroboros(OURO_NONCE, OURO_EPOCH, table);
  }

  buildProof(block: JsonValue): JsonValue {
    const header = headerFromBlock(block);
    const cid = blockId(header);
    const slot = header['height'];
    const parent = this.chainToOuro.get(String(header['parent'] ?? '')) ?? '';
    const leader = header['producer'];
    if (!isInt(slot) || typeof leader !== 'string') throw new Error('header');
    const table = ouroTable();
    const scratch = new Ouroboros(OURO_NONCE, OURO_EPOCH, table);
    const order = this.ouro.state().blocks;
    for (const mid of order) {
      const msg = this.ouroMessages.get(mid);
      if (msg !== undefined) scratch.addMessage(msg);
    }
    const parentRecord =
      parent === ''
        ? undefined
        : (scratch as unknown as { blocks: Map<string, unknown> }).blocks.get(parent);
    const ctx = (
      scratch as unknown as {
        epochNonceForSlot(
          slot: number,
          parent: unknown,
        ): { epoch: number; nonce: string };
      }
    ).epochNonceForSlot(slot, parentRecord);
    const sk = ouroKeys().get(leader);
    if (sk === undefined) throw new Error('leader key');
    const vrfMessage = (
      scratch as unknown as {
        vrfMessage(epoch: number, nonce: string, slot: number, leader: string): Uint8Array;
      }
    ).vrfMessage(ctx.epoch, ctx.nonce, slot, leader);
    const result = vrf.evaluate(vrfMessage, sk);
    return {
      consensus: 'ouroboros',
      slot,
      parent,
      payload: cid,
      leader,
      pk: bytesToHex(result.publicKey),
      proof: bytesToHex(result.proof),
      output: bytesToHex(result.output),
    };
  }

  authorize(block: JsonValue, proof: JsonValue): boolean {
    const obj = asRecord(proof);
    if (obj === undefined || obj['consensus'] !== 'ouroboros') return false;
    const header = headerFromBlockOpt(block);
    if (header === undefined) return false;
    let cid: string;
    try {
      cid = blockId(header);
    } catch {
      return false;
    }
    if (obj['payload'] !== cid) return false;
    if (!this.ouro.isValid(proof)) return false;
    this.ouro.addMessage(proof);
    const slot = obj['slot'];
    const parent = obj['parent'];
    const payload = obj['payload'];
    const leader = obj['leader'];
    const pk = obj['pk'];
    const proofHex = obj['proof'];
    const output = obj['output'];
    if (
      !isInt(slot) ||
      typeof parent !== 'string' ||
      typeof payload !== 'string' ||
      typeof leader !== 'string' ||
      typeof pk !== 'string' ||
      typeof proofHex !== 'string' ||
      typeof output !== 'string'
    ) {
      return false;
    }
    let digest: string;
    try {
      digest = ouroborosBlockId(slot, parent, payload, leader, pk, proofHex, output);
    } catch {
      return false;
    }
    this.ouroMessages.set(digest, proof);
    this.chainToOuro.set(cid, digest);
    return true;
  }

  canonical(): string[] {
    const { canonical } = this.ouro.state();
    const payloads: string[] = [];
    for (const digest of canonical) {
      const msg = this.ouroMessages.get(digest);
      const mobj = msg === undefined ? undefined : asRecord(msg);
      const payload = mobj?.['payload'];
      if (typeof payload === 'string') payloads.push(payload);
    }
    return payloads;
  }
}