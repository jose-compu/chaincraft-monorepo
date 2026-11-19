/** Proof-of-transfer object — SPEC/features/consensus-pox.md. */

import type { JsonValue } from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';

const MAX_INT = 9007199254740991;
const SEED_RE = /^[0-9a-f]{64}$/;

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= MAX_INT;
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

export function rewardCycle(height: number, cycleLength: number): number {
  if (height < 1) return 0;
  return Math.floor((height - 1) / cycleLength);
}

export function stackId(locker: string, amount: number, rewardCycle: number): string {
  return merkleDigest({ amount, kind: 'stack', locker, reward_cycle: rewardCycle });
}

export function bidId(miner: string, btcOut: number, blockHeight: number): string {
  return merkleDigest({ block_height: blockHeight, btc_out: btcOut, kind: 'bid', miner });
}

export function tenureId(winner: string, prev: string, blockHeight: number): string {
  return merkleDigest({ block_height: blockHeight, kind: 'tenure', prev, winner });
}

export function sortitionScore(
  seed: string,
  miner: string,
  btcOut: number,
  blockHeight: number,
): string {
  return merkleDigest({ block_height: blockHeight, btc_out: btcOut, miner, seed });
}

interface StackRecord {
  locker: string;
  amount: number;
  reward_cycle: number;
}

interface BidRecord {
  miner: string;
  btc_out: number;
  block_height: number;
}

interface TenureRecord {
  winner: string;
  prev: string;
  block_height: number;
}

type Parsed =
  | { kind: 'stack'; digest: string; record: StackRecord }
  | { kind: 'bid'; digest: string; record: BidRecord }
  | { kind: 'tenure'; digest: string; record: TenureRecord };

export class ProofOfTransfer extends BaseSharedObject {
  readonly seed: string;
  readonly cycleLength: number;
  private readonly snapshot0: readonly { locker: string; amount: number }[];
  private readonly stacks = new Map<string, StackRecord>();
  private readonly stackOrder: string[] = [];
  private readonly stacksByCycle = new Map<number, Set<string>>();
  private readonly bids = new Map<string, BidRecord>();
  private readonly bidOrder: string[] = [];
  private readonly bidsByHeight = new Map<number, Map<string, string>>();
  private readonly tenures = new Map<string, TenureRecord>();
  private readonly tenureOrder: string[] = [];
  private openHeight = 1;

  constructor(
    seed: string,
    cycleLength: number,
    stackers: readonly { locker: string; amount: number }[],
  ) {
    super();
    if (!SEED_RE.test(seed)) {
      throw new RangeError('seed must be 64 lowercase hex characters');
    }
    if (!isInt(cycleLength) || cycleLength < 1) {
      throw new RangeError('cycle_length must be an integer >= 1');
    }
    if (stackers.length === 0) {
      throw new RangeError('stackers must be non-empty');
    }
    const seen = new Set<string>();
    const snapshot0: { locker: string; amount: number }[] = [];
    for (const { locker, amount } of stackers) {
      if (typeof locker !== 'string' || locker.length === 0) {
        throw new RangeError('each locker must be a non-empty string');
      }
      if (!isInt(amount) || amount < 1) {
        throw new RangeError('each amount must be an integer >= 1');
      }
      if (seen.has(locker)) {
        throw new RangeError('lockers must be distinct');
      }
      seen.add(locker);
      snapshot0.push({ locker, amount });
    }
    this.seed = seed;
    this.cycleLength = cycleLength;
    this.snapshot0 = snapshot0;
  }

  override isValid(message: JsonValue): boolean {
    return this.parse(message) !== undefined;
  }

  override addMessage(
    message: JsonValue,
    _frontierState?: StateMemento | undefined,
  ): StateMemento | undefined {
    const parsed = this.parse(message);
    if (parsed === undefined) return this.emitStateMemento();
    if (parsed.kind === 'stack') {
      this.stacks.set(parsed.digest, parsed.record);
      this.stackOrder.push(parsed.digest);
      const cycleSet =
        this.stacksByCycle.get(parsed.record.reward_cycle) ?? new Set<string>();
      cycleSet.add(parsed.record.locker);
      this.stacksByCycle.set(parsed.record.reward_cycle, cycleSet);
    } else if (parsed.kind === 'bid') {
      this.bids.set(parsed.digest, parsed.record);
      this.bidOrder.push(parsed.digest);
      const miners =
        this.bidsByHeight.get(parsed.record.block_height) ?? new Map<string, string>();
      miners.set(parsed.record.miner, parsed.digest);
      this.bidsByHeight.set(parsed.record.block_height, miners);
    } else {
      this.tenures.set(parsed.digest, parsed.record);
      this.tenureOrder.push(parsed.digest);
      this.openHeight = parsed.record.block_height + 1;
    }
    return this.emitStateMemento();
  }

  override emitStateMemento(): StateMemento {
    const tip = this.tip();
    return StateMemento.normalize(
      merkleDigest({ height: tip.height, tip: tip.id, v: 1 }),
      [],
    );
  }

  override getStateDigests(): string[] {
    const tip = this.tip();
    return tip.id ? [tip.id] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): {
    height: number;
    tip: string;
    open_height: number;
    cycle: number;
    canonical: string[];
    tenures: string[];
    bids: string[];
    stacks: string[];
  } {
    const tip = this.tip();
    return {
      height: tip.height,
      tip: tip.id,
      open_height: this.openHeight,
      cycle: rewardCycle(this.openHeight, this.cycleLength),
      canonical: this.canonical(tip.id),
      tenures: [...this.tenureOrder],
      bids: [...this.bidOrder],
      stacks: [...this.stackOrder],
    };
  }

  private tip(): { id: string; height: number } {
    let id = '';
    let height = 0;
    for (const [digest, record] of this.tenures) {
      if (
        record.block_height > height ||
        (record.block_height === height && (id === '' || digest < id))
      ) {
        id = digest;
        height = record.block_height;
      }
    }
    return { id, height };
  }

  private canonical(tip: string): string[] {
    const chain: string[] = [];
    let cursor = tip;
    while (cursor !== '') {
      chain.push(cursor);
      cursor = this.tenures.get(cursor)?.prev ?? '';
    }
    chain.reverse();
    return chain;
  }

  private snapshotLockers(cycle: number): Set<string> {
    if (cycle === 0) {
      return new Set(this.snapshot0.map((s) => s.locker));
    }
    const lockers = new Set<string>();
    for (const digest of this.stackOrder) {
      const record = this.stacks.get(digest);
      if (record !== undefined && record.reward_cycle === cycle) {
        lockers.add(record.locker);
      }
    }
    return lockers;
  }

  private electedMiner(blockHeight: number): string | undefined {
    const miners = this.bidsByHeight.get(blockHeight);
    if (miners === undefined || miners.size === 0) return undefined;
    let bestMiner: string | undefined;
    let bestScore = '';
    let bestId = '';
    for (const [miner, digest] of miners) {
      const record = this.bids.get(digest);
      if (record === undefined) continue;
      const score = sortitionScore(this.seed, miner, record.btc_out, blockHeight);
      if (
        bestMiner === undefined ||
        score < bestScore ||
        (score === bestScore && digest < bestId)
      ) {
        bestMiner = miner;
        bestScore = score;
        bestId = digest;
      }
    }
    return bestMiner;
  }

  private containsId(digest: string): boolean {
    return this.stacks.has(digest) || this.bids.has(digest) || this.tenures.has(digest);
  }

  private parse(message: JsonValue): Parsed | undefined {
    const obj = asRecord(message);
    if (obj === undefined || obj['consensus'] !== 'pox') return undefined;
    const kind = obj['kind'];
    if (kind === 'stack') return this.parseStack(obj);
    if (kind === 'bid') return this.parseBid(obj);
    if (kind === 'tenure') return this.parseTenure(obj);
    return undefined;
  }

  private parseStack(obj: Record<string, JsonValue>): Parsed | undefined {
    const locker = obj['locker'];
    const amount = obj['amount'];
    const rewardCycleVal = obj['reward_cycle'];
    if (typeof locker !== 'string' || locker.length === 0) return undefined;
    if (!isInt(amount) || amount < 1) return undefined;
    if (!isInt(rewardCycleVal) || rewardCycleVal < 1) return undefined;
    const openCycle = rewardCycle(this.openHeight, this.cycleLength);
    if (rewardCycleVal <= openCycle) return undefined;
    const cycleSet = this.stacksByCycle.get(rewardCycleVal);
    if (cycleSet?.has(locker)) return undefined;
    const digest = stackId(locker, amount, rewardCycleVal);
    if (this.containsId(digest)) return undefined;
    return {
      kind: 'stack',
      digest,
      record: { locker, amount, reward_cycle: rewardCycleVal },
    };
  }

  private parseBid(obj: Record<string, JsonValue>): Parsed | undefined {
    const miner = obj['miner'];
    const btcOut = obj['btc_out'];
    const blockHeight = obj['block_height'];
    if (typeof miner !== 'string' || miner.length === 0) return undefined;
    if (!isInt(btcOut) || btcOut < 1) return undefined;
    if (!isInt(blockHeight) || blockHeight !== this.openHeight) return undefined;
    const cycle = rewardCycle(blockHeight, this.cycleLength);
    if (!this.snapshotLockers(cycle).has(miner)) return undefined;
    const miners = this.bidsByHeight.get(blockHeight);
    if (miners?.has(miner)) return undefined;
    const digest = bidId(miner, btcOut, blockHeight);
    if (this.containsId(digest)) return undefined;
    return {
      kind: 'bid',
      digest,
      record: { miner, btc_out: btcOut, block_height: blockHeight },
    };
  }

  private parseTenure(obj: Record<string, JsonValue>): Parsed | undefined {
    const winner = obj['winner'];
    const prev = obj['prev'];
    const blockHeight = obj['block_height'];
    if (typeof winner !== 'string' || winner.length === 0) return undefined;
    if (typeof prev !== 'string') return undefined;
    if (!isInt(blockHeight) || blockHeight !== this.openHeight) return undefined;
    const elected = this.electedMiner(blockHeight);
    if (elected === undefined || winner !== elected) return undefined;
    const tip = this.tip();
    if (blockHeight === 1) {
      if (prev !== '') return undefined;
    } else if (prev !== tip.id) {
      return undefined;
    }
    const digest = tenureId(winner, prev, blockHeight);
    if (this.containsId(digest)) return undefined;
    return {
      kind: 'tenure',
      digest,
      record: { winner, prev, block_height: blockHeight },
    };
  }
}