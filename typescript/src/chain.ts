/** Transfer chain — SPEC/features/chain-transfer.md. */

import { sha256 } from '@noble/hashes/sha2.js';
import {
  type JsonValue,
  MAX_SAFE_INT,
  bytesToHex,
  canonicalBytes,
  compareCodePoints,
  hexToBytes,
} from './canonical.ts';
import { SCHNORR, sign, verify } from './crypto.ts';
import { merkleDigest } from './object.ts';

const HEX64 = /^[0-9a-f]{64}$/;
const SIG128 = /^[0-9a-f]{128}$/;

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(value: JsonValue): Record<string, JsonValue> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, JsonValue>;
}

export function normalizeGenesis(genesis: Readonly<Record<string, number>>): Record<string, number> {
  if (Object.keys(genesis).length === 0) {
    throw new Error('genesis must not be empty');
  }
  const out: Record<string, number> = {};
  for (const account of Object.keys(genesis)) {
    const amount = genesis[account];
    if (!account) throw new Error('account id must be non-empty');
    if (
      amount === undefined ||
      !Number.isSafeInteger(amount) ||
      amount < 1 ||
      amount > MAX_SAFE_INT
    ) {
      throw new Error('each balance must be an integer in 1..2^53-1');
    }
    out[account] = amount;
  }
  return out;
}

export function transactionId(body: JsonValue): string {
  return merkleDigest(body);
}

export function transferSigningBytes(body: JsonValue): Uint8Array {
  return sha256(canonicalBytes(body));
}

function parseBody(body: JsonValue): Record<string, JsonValue> | undefined {
  const obj = asRecord(body);
  if (obj === undefined) return undefined;
  const amount = obj['amount'];
  const fee = obj['fee'];
  const nonce = obj['nonce'];
  const recipient = obj['recipient'];
  const sender = obj['sender'];
  if (!isInt(amount) || amount < 1) return undefined;
  if (!isInt(fee) || fee < 0) return undefined;
  if (!isInt(nonce) || nonce < 0) return undefined;
  if (typeof recipient !== 'string' || recipient.length === 0) return undefined;
  if (typeof sender !== 'string' || !HEX64.test(sender)) return undefined;
  return { amount, fee, nonce, recipient, sender };
}

export function verifyTransfer(tx: JsonValue): boolean {
  const obj = asRecord(tx);
  if (obj === undefined) return false;
  const signature = obj['signature'];
  if (typeof signature !== 'string' || !SIG128.test(signature)) return false;
  const body: Record<string, JsonValue> = {};
  for (const [key, value] of Object.entries(obj)) {
    if (key !== 'signature') body[key] = value;
  }
  const parsed = parseBody(body);
  if (parsed === undefined) return false;
  let signing: Uint8Array;
  try {
    signing = transferSigningBytes(parsed);
  } catch {
    return false;
  }
  let sigBytes: Uint8Array;
  let pkBytes: Uint8Array;
  try {
    sigBytes = hexToBytes(signature);
    if (sigBytes.length !== 64) return false;
    const sender = parsed['sender'];
    if (typeof sender !== 'string') return false;
    pkBytes = hexToBytes(sender);
    if (pkBytes.length !== 32) return false;
  } catch {
    return false;
  }
  return verify(SCHNORR, signing, sigBytes, pkBytes);
}

export function signTransfer(
  body: JsonValue,
  secretKey: Uint8Array,
  aux?: Uint8Array,
): JsonValue {
  const parsed = parseBody(body);
  if (parsed === undefined) throw new Error('invalid transfer body');
  const signing = transferSigningBytes(parsed);
  const result = sign(SCHNORR, signing, secretKey, aux);
  return { ...parsed, signature: bytesToHex(result.signature) };
}

export function blockId(header: JsonValue): string {
  return merkleDigest(header);
}

function txBody(tx: Record<string, JsonValue>): Record<string, JsonValue> {
  const out: Record<string, JsonValue> = {};
  for (const [key, value] of Object.entries(tx)) {
    if (key !== 'signature') out[key] = value;
  }
  return out;
}

function sortedNumericMap(values: Record<string, number>): Record<string, JsonValue> {
  const out: Record<string, JsonValue> = {};
  for (const key of Object.keys(values).sort(compareCodePoints)) {
    out[key] = values[key]!;
  }
  return out;
}

function applyTx(
  reward: number,
  tx: JsonValue,
  producer: string,
  balances: Record<string, number>,
  nonces: Record<string, number>,
): boolean {
  if (!verifyTransfer(tx)) return false;
  const body = asRecord(txBody(tx as Record<string, JsonValue>));
  if (body === undefined) return false;
  const sender = body['sender'];
  const recipient = body['recipient'];
  const amount = body['amount'];
  const fee = body['fee'];
  const nonce = body['nonce'];
  if (
    typeof sender !== 'string' ||
    typeof recipient !== 'string' ||
    !isInt(amount) ||
    !isInt(fee) ||
    !isInt(nonce)
  ) {
    return false;
  }
  if (nonce !== (nonces[sender] ?? 0)) return false;
  const senderBal = balances[sender] ?? 0;
  if (senderBal < amount + fee) return false;
  if ((balances[recipient] ?? 0) + amount > MAX_SAFE_INT) return false;
  const producerCredit = fee + reward;
  if ((balances[producer] ?? 0) + producerCredit > MAX_SAFE_INT) return false;
  balances[sender] = senderBal - amount - fee;
  balances[recipient] = (balances[recipient] ?? 0) + amount;
  balances[producer] = (balances[producer] ?? 0) + producerCredit;
  nonces[sender] = nonce + 1;
  if (nonces[recipient] === undefined) nonces[recipient] = 0;
  if (nonces[producer] === undefined) nonces[producer] = 0;
  return true;
}

class ChainMempool {
  private readonly txs = new Map<string, JsonValue>();

  submit(tx: JsonValue): boolean {
    if (!verifyTransfer(tx)) return false;
    const obj = asRecord(tx);
    if (obj === undefined) return false;
    const body = txBody(obj);
    const tid = transactionId(body);
    this.txs.set(tid, tx);
    return true;
  }

  ordered(): JsonValue[] {
    const items = [...this.txs.values()];
    items.sort((a, b) => {
      const bodyA = txBody(a as Record<string, JsonValue>);
      const bodyB = txBody(b as Record<string, JsonValue>);
      const feeA = bodyA['fee'];
      const feeB = bodyB['fee'];
      const fa = isInt(feeA) ? feeA : 0;
      const fb = isInt(feeB) ? feeB : 0;
      const tidA = transactionId(bodyA);
      const tidB = transactionId(bodyB);
      if (fb !== fa) return fb - fa;
      return tidA < tidB ? -1 : tidA > tidB ? 1 : 0;
    });
    return items;
  }

  remove(ids: readonly string[]): void {
    for (const tid of ids) this.txs.delete(tid);
  }
}

export interface ChainDriver {
  buildProof(block: JsonValue): JsonValue;
  authorize(block: JsonValue, proof: JsonValue): boolean;
  canonical(): string[];
}

export class TransferChain {
  private readonly genesis: Record<string, number>;
  private readonly reward: number;
  private driver: ChainDriver | undefined;
  private readonly blocks = new Map<string, JsonValue>();
  private readonly mempool = new ChainMempool();
  private balances: Record<string, number>;
  private nonces: Record<string, number>;
  private canonical: string[] = [];
  private height = 0;
  private tip = '';

  constructor(
    genesis: Readonly<Record<string, number>>,
    reward = 0,
    driver?: ChainDriver,
  ) {
    if (!Number.isSafeInteger(reward) || reward < 0) {
      throw new Error('reward must be >= 0');
    }
    this.genesis = normalizeGenesis(genesis);
    this.reward = reward;
    this.driver = driver;
    this.balances = { ...this.genesis };
    this.nonces = Object.fromEntries(Object.keys(this.genesis).map((k) => [k, 0]));
  }

  setDriver(driver: ChainDriver): void {
    this.driver = driver;
  }

  submit(tx: JsonValue): boolean {
    if (asRecord(tx) === undefined) return false;
    return this.mempool.submit(tx);
  }

  private txRoot(txs: readonly JsonValue[]): string {
    const ids: JsonValue[] = [];
    for (const tx of txs) {
      const obj = asRecord(tx);
      if (obj === undefined) throw new Error('tx');
      ids.push(transactionId(txBody(obj)));
    }
    return merkleDigest(ids);
  }

  private applyTxLocal(
    tx: JsonValue,
    producer: string,
    balances: Record<string, number>,
    nonces: Record<string, number>,
  ): boolean {
    return applyTx(this.reward, tx, producer, balances, nonces);
  }

  private applyBlockTransactions(
    txs: readonly JsonValue[],
    producer: string,
    balances: Record<string, number>,
    nonces: Record<string, number>,
  ): boolean {
    for (const tx of txs) {
      if (!this.applyTxLocal(tx, producer, balances, nonces)) return false;
    }
    return true;
  }

  private replayCanonical(canon: readonly string[]): void {
    this.balances = { ...this.genesis };
    this.nonces = Object.fromEntries(Object.keys(this.genesis).map((k) => [k, 0]));
    this.canonical = [];
    this.height = 0;
    this.tip = '';
    for (const bid of canon) {
      const block = this.blocks.get(bid);
      if (block === undefined) return;
      const obj = asRecord(block);
      if (obj === undefined) return;
      const headerRaw = obj['header'];
      const header = headerRaw === undefined ? undefined : asRecord(headerRaw);
      const txs = obj['transactions'];
      if (header === undefined || !Array.isArray(txs)) return;
      const producer = header['producer'];
      if (typeof producer !== 'string') return;
      for (const tx of txs) {
        if (!applyTx(this.reward, tx, producer, this.balances, this.nonces)) return;
      }
      this.canonical.push(bid);
      const height = header['height'];
      if (isInt(height)) this.height = height;
      this.tip = bid;
    }
  }

  private validateHeader(header: JsonValue, parentId: string): boolean {
    const obj = asRecord(header);
    if (obj === undefined) return false;
    const height = obj['height'];
    const parent = obj['parent'];
    const producer = obj['producer'];
    const stateRoot = obj['state_root'];
    const time = obj['time'];
    const txRoot = obj['tx_root'];
    if (!isInt(height) || height < 1) return false;
    if (typeof parent !== 'string') return false;
    if (typeof producer !== 'string' || producer.length === 0) return false;
    if (typeof stateRoot !== 'string' || !HEX64.test(stateRoot)) return false;
    if (!isInt(time) || time < 0) return false;
    if (typeof txRoot !== 'string' || !HEX64.test(txRoot)) return false;
    if (height === 1) return parent === '';
    return parent === parentId && this.blocks.has(parentId);
  }

  private canonicalForParent(parentId: string): string[] {
    if (parentId === '') return [];
    if (this.driver !== undefined) {
      const canon = this.driver.canonical();
      const idx = canon.indexOf(parentId);
      if (idx >= 0) return canon.slice(0, idx + 1);
    }
    const chain: string[] = [];
    let cursor = parentId;
    while (cursor !== '') {
      chain.push(cursor);
      const block = this.blocks.get(cursor);
      if (block === undefined) break;
      const obj = asRecord(block);
      const headerRaw = obj?.['header'];
      const header = headerRaw === undefined ? undefined : asRecord(headerRaw);
      const parent = header?.['parent'];
      cursor = typeof parent === 'string' ? parent : '';
    }
    chain.reverse();
    return chain;
  }

  private validateBlockRecord(block: JsonValue, checkDriver: boolean): boolean {
    const obj = asRecord(block);
    if (obj === undefined || obj['chain'] !== 'transfer') return false;
    const txs = obj['transactions'];
    if (!Array.isArray(txs)) return false;
    const headerVal = obj['header'];
    if (headerVal === undefined) return false;
    let parentId = '';
    const hdrCheck = asRecord(headerVal);
    if (hdrCheck !== undefined && isInt(hdrCheck['height']) && hdrCheck['height'] > 1) {
      const parent = hdrCheck['parent'];
      parentId = typeof parent === 'string' ? parent : '';
    }
    if (!this.validateHeader(headerVal, parentId)) return false;
    const hdr = asRecord(headerVal);
    if (hdr === undefined) return false;
    let bid: string;
    try {
      bid = blockId(hdr);
    } catch {
      return false;
    }
    if (this.blocks.has(bid)) return false;
    for (const tx of txs) {
      if (!verifyTransfer(tx)) return false;
    }
    try {
      if (this.txRoot(txs) !== hdr['tx_root']) return false;
    } catch {
      return false;
    }
    const balances = { ...this.genesis };
    const nonces = Object.fromEntries(Object.keys(this.genesis).map((k) => [k, 0]));
    const height = hdr['height'];
    if (isInt(height) && height > 1) {
      const parent = hdr['parent'];
      if (typeof parent !== 'string') return false;
      const chainPrefix = this.canonicalForParent(parent);
      for (const pid of chainPrefix) {
        const pb = this.blocks.get(pid);
        const pobj = pb === undefined ? undefined : asRecord(pb);
        if (pobj === undefined) return false;
        const ptxs = pobj['transactions'];
        const pheaderRaw = pobj['header'];
        const pheader = pheaderRaw === undefined ? undefined : asRecord(pheaderRaw);
        if (!Array.isArray(ptxs) || pheader === undefined) return false;
        const pprod = pheader['producer'];
        if (typeof pprod !== 'string') return false;
        if (!this.applyBlockTransactions(ptxs, pprod, balances, nonces)) return false;
      }
    }
    const producer = hdr['producer'];
    if (typeof producer !== 'string') return false;
    if (!this.applyBlockTransactions(txs, producer, balances, nonces)) return false;
    const snap: JsonValue = {
      balances: sortedNumericMap(balances),
      nonces: sortedNumericMap(nonces),
      v: 1,
    };
    try {
      if (merkleDigest(snap) !== hdr['state_root']) return false;
    } catch {
      return false;
    }
    if (checkDriver && this.driver !== undefined) {
      const proof = obj['proof'] ?? {};
      if (!this.driver.authorize(block, proof)) return false;
    }
    return true;
  }

  acceptBlock(block: JsonValue): boolean {
    if (asRecord(block) === undefined) return false;
    if (!this.validateBlockRecord(block, true)) return false;
    const obj = asRecord(block);
    if (obj === undefined) return false;
    const headerRaw = obj['header'];
    const header = headerRaw === undefined ? undefined : asRecord(headerRaw);
    if (header === undefined) return false;
    const bid = blockId(header);
    this.blocks.set(bid, block);
    if (this.driver !== undefined) {
      this.replayCanonical(this.driver.canonical());
    } else {
      this.replayCanonical(this.extendCanonical(bid));
    }
    return true;
  }

  private extendCanonical(bid: string): string[] {
    const chain: string[] = [];
    let cursor = bid;
    while (cursor !== '') {
      chain.push(cursor);
      const block = this.blocks.get(cursor);
      const obj = block === undefined ? undefined : asRecord(block);
      const headerRaw = obj?.['header'];
      const header = headerRaw === undefined ? undefined : asRecord(headerRaw);
      const parent = header?.['parent'];
      cursor = typeof parent === 'string' ? parent : '';
    }
    chain.reverse();
    return chain;
  }

  produce(time: number, producer: string): JsonValue | undefined {
    if (!Number.isSafeInteger(time) || time < 0) throw new Error('time must be >= 0');
    if (!producer) throw new Error('producer required');
    const parent = this.tip;
    const height = this.height + 1;
    const balances = { ...this.balances };
    const nonces = { ...this.nonces };
    const included: JsonValue[] = [];
    const includedIds: string[] = [];
    for (const tx of this.mempool.ordered()) {
      const obj = asRecord(tx);
      if (obj === undefined) continue;
      const body = txBody(obj);
      const tid = transactionId(body);
      const trialBal = { ...balances };
      const trialNon = { ...nonces };
      if (this.applyTxLocal(tx, producer, trialBal, trialNon)) {
        included.push(tx);
        includedIds.push(tid);
        Object.assign(balances, trialBal);
        Object.assign(nonces, trialNon);
      } else {
        break;
      }
    }
    const snap: JsonValue = {
      balances: sortedNumericMap(balances),
      nonces: sortedNumericMap(nonces),
      v: 1,
    };
    const header: JsonValue = {
      height,
      parent,
      producer,
      state_root: merkleDigest(snap),
      time,
      tx_root: this.txRoot(included),
    };
    let block: JsonValue = {
      chain: 'transfer',
      header,
      transactions: included,
      proof: {},
    };
    if (this.driver !== undefined) {
      const proof = this.driver.buildProof(block);
      const bobj = asRecord(block);
      if (bobj !== undefined) bobj['proof'] = proof;
    }
    if (!this.acceptBlock(block)) return undefined;
    this.mempool.remove(includedIds);
    return block;
  }

  importBlocks(blocks: readonly JsonValue[]): boolean {
    for (const block of blocks) {
      if (!this.acceptBlock(block)) return false;
    }
    return true;
  }

  state(): JsonValue {
    return {
      balances: sortedNumericMap(this.balances),
      nonces: sortedNumericMap(this.nonces),
      canonical: this.canonical,
      height: this.height,
      tip: this.tip,
    };
  }
}