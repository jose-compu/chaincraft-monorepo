/** Node preset — SPEC/features/node-preset.md. */

import type { JsonValue } from './canonical.ts';
import { TransferChain } from './chain.ts';
import { makeDriver, OURO_EPOCH, OURO_NONCE, ouroTable } from './chainDriver.ts';
import { Avalanche } from './consensusAvalanche.ts';
import { RandomnessBeacon } from './consensusBeacon.ts';
import { Ouroboros } from './consensusOuroboros.ts';
import { PBFT } from './consensusPbft.ts';
import { ProofOfAuthority } from './consensusPoa.ts';
import { ProofOfElapsedTime } from './consensusPoet.ts';
import { ProofOfStake } from './consensusPos.ts';
import { ProofOfWork } from './consensusPow.ts';
import { ProofOfTransfer } from './consensusPox.ts';
import { CrdtKv } from './crdt.ts';
import { BalanceLedger, DEFAULT_ALLOCATIONS as BALANCE_DEFAULT } from './ledgerBalance.ts';
import { UtxoLedger, DEFAULT_ALLOCATIONS as UTXO_DEFAULT } from './ledgerUtxo.ts';
import { Mesh, parseListen } from './mesh.ts';
import { PubSub } from './pubsub.ts';

const CONSENSUS = new Set([
  'pow',
  'poa',
  'pos',
  'pbft',
  'poet',
  'avalanche',
  'beacon',
  'pox',
  'ouroboros',
]);

const PROTOCOLS = new Set(['transfer', 'balance', 'utxo', 'crdt', 'pubsub', ...CONSENSUS]);

const CONSENSUS_EXTRA: Record<string, ReadonlySet<string>> = {
  pow: new Set(['difficulty']),
  poa: new Set(['authorities']),
  pbft: new Set(['replicas']),
  poet: new Set(['seed']),
  pox: new Set(['seed', 'cycle_length', 'stackers']),
};

function isWireInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function consensusAllowed(protocol: string): Set<string> {
  const base = new Set(['protocol', 'listen', 'peers', 'udp']);
  const extra = CONSENSUS_EXTRA[protocol];
  if (extra !== undefined) {
    for (const key of extra) base.add(key);
  }
  return base;
}

type PresetObject =
  | BalanceLedger
  | UtxoLedger
  | CrdtKv
  | PubSub
  | ProofOfWork
  | ProofOfAuthority
  | ProofOfStake
  | PBFT
  | ProofOfElapsedTime
  | Avalanche
  | RandomnessBeacon
  | ProofOfTransfer
  | Ouroboros;

function isValidObject(obj: PresetObject, message: JsonValue): boolean {
  return obj.isValid(message);
}

function addObjectMessage(obj: PresetObject, message: JsonValue): void {
  obj.addMessage(message);
}

function rejectUnknown(config: Record<string, JsonValue>, allowed: ReadonlySet<string>): void {
  for (const key of Object.keys(config)) {
    if (!allowed.has(key)) throw new Error(`unknown config key: ${key}`);
  }
}

function jsonI64Map(value: JsonValue): Record<string, number> {
  const obj = value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, JsonValue>)
    : undefined;
  if (obj === undefined) throw new Error('genesis must be an object');
  const map: Record<string, number> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v !== 'number' || !Number.isSafeInteger(v)) {
      throw new Error('genesis values must be integers');
    }
    map[k] = v;
  }
  return map;
}

function jsonBool(value: JsonValue | undefined): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function consensusObject(protocol: string, config: Record<string, JsonValue>): PresetObject {
  switch (protocol) {
    case 'poa': {
      const authorities = stringList(config['authorities']) ?? ['alice'];
      return new ProofOfAuthority(authorities);
    }
    case 'pow': {
      const difficulty =
        typeof config['difficulty'] === 'number' && Number.isSafeInteger(config['difficulty'])
          ? config['difficulty']
          : 2;
      return new ProofOfWork(difficulty);
    }
    case 'pos':
      return new ProofOfStake();
    case 'pbft': {
      const replicas = stringList(config['replicas']);
      return replicas === undefined ? new PBFT() : new PBFT(replicas);
    }
    case 'poet': {
      const seed =
        typeof config['seed'] === 'string' ? config['seed'] : 'chaincraft-poet-genesis';
      return new ProofOfElapsedTime(seed);
    }
    case 'avalanche':
      return new Avalanche('slush');
    case 'beacon':
      return new RandomnessBeacon();
    case 'pox': {
      const defaultSeed = '0'.repeat(64);
      const seed = typeof config['seed'] === 'string' ? config['seed'] : defaultSeed;
      const cycle =
        typeof config['cycle_length'] === 'number' && Number.isSafeInteger(config['cycle_length'])
          ? config['cycle_length']
          : 3;
      const stackers =
        config['stackers'] === undefined
          ? [{ locker: 'alice', amount: 100 }]
          : parseStackers(config['stackers']);
      return new ProofOfTransfer(seed, cycle, stackers);
    }
    case 'ouroboros':
      return new Ouroboros(OURO_NONCE, OURO_EPOCH, ouroTable());
    default:
      throw new Error('invalid protocol');
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

function parseStackers(value: JsonValue | undefined): { locker: string; amount: number }[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new RangeError('stackers must be non-empty');
  }
  const out: { locker: string; amount: number }[] = [];
  for (const item of value) {
    if (Array.isArray(item)) {
      throw new RangeError('stackers entry must be an object');
    }
    if (item === null || typeof item !== 'object') {
      throw new RangeError('stackers entry must be an object');
    }
    const locker = (item as Record<string, JsonValue>)['locker'];
    const amount = (item as Record<string, JsonValue>)['amount'];
    if (typeof locker !== 'string' || locker.length === 0) {
      throw new RangeError('each locker must be a non-empty string');
    }
    if (!isWireInt(amount) || amount < 1) {
      throw new RangeError('each amount must be an integer >= 1');
    }
    out.push({ locker, amount });
  }
  return out;
}

function validateConsensusConfig(protocol: string, config: Record<string, JsonValue>): void {
  rejectUnknown(config, consensusAllowed(protocol));
  if (protocol === 'pow' && config['difficulty'] !== undefined) {
    const difficulty = config['difficulty'];
    if (!isWireInt(difficulty) || difficulty < 1 || difficulty > 64) {
      throw new RangeError('difficulty must be in 1..64');
    }
  }
  if (protocol === 'poa' && config['authorities'] !== undefined) {
    const authorities = config['authorities'];
    if (!Array.isArray(authorities) || authorities.length === 0) {
      throw new RangeError('authorities must be non-empty');
    }
    const seen = new Set<string>();
    for (const authority of authorities) {
      if (typeof authority !== 'string' || authority.length === 0) {
        throw new RangeError('each authority must be a non-empty string');
      }
      if (seen.has(authority)) throw new RangeError('authorities must be distinct');
      seen.add(authority);
    }
  }
  if (protocol === 'pbft' && config['replicas'] !== undefined) {
    const replicas = stringList(config['replicas']);
    if (replicas === undefined || replicas.length === 0 || new Set(replicas).size !== replicas.length) {
      throw new RangeError('replicas must be unique non-empty ids');
    }
  }
  if (protocol === 'poet' && config['seed'] !== undefined) {
    const seed = config['seed'];
    if (typeof seed !== 'string' || seed.length === 0) {
      throw new RangeError('seed must be a non-empty string');
    }
  }
  if (protocol === 'pox') {
    if (config['seed'] !== undefined) {
      const seed = config['seed'];
      if (typeof seed !== 'string' || !/^[0-9a-f]{64}$/.test(seed)) {
        throw new RangeError('seed must be 64 lowercase hex characters');
      }
    }
    if (config['cycle_length'] !== undefined) {
      const cycle = config['cycle_length'];
      if (!isWireInt(cycle) || cycle < 1) {
        throw new RangeError('cycle_length must be an integer >= 1');
      }
    }
    if (config['stackers'] !== undefined) {
      parseStackers(config['stackers']);
    }
  }
}

export class PresetHandle {
  readonly listenAddr: string;
  private readonly chain: TransferChain | undefined;
  private readonly object: PresetObject | undefined;
  readonly protocol: string;
  private readonly mesh: Mesh;

  constructor(
    listenAddr: string,
    protocol: string,
    mesh: Mesh,
    chain?: TransferChain,
    object?: PresetObject,
  ) {
    this.listenAddr = listenAddr;
    this.protocol = protocol;
    this.mesh = mesh;
    this.chain = chain;
    this.object = object;
  }

  state(): JsonValue {
    if (this.chain !== undefined) return this.chain.state();
    if (this.object !== undefined && 'state' in this.object) {
      return (this.object as { state(): JsonValue }).state();
    }
    return {};
  }

  submit(message: JsonValue): boolean {
    if (this.protocol === 'transfer') {
      const chain = this.chain;
      if (chain === undefined) return false;
      const obj =
        message !== null && typeof message === 'object' && !Array.isArray(message)
          ? (message as Record<string, JsonValue>)
          : undefined;
      if (obj !== undefined && obj['chain'] === 'transfer') {
        if (chain.acceptBlock(message)) {
          this.mesh.broadcast('app.transfer', message);
          return true;
        }
        return false;
      }
      if (chain.submit(message)) {
        this.mesh.broadcast('app.transfer', message);
        return true;
      }
      return false;
    }
    const object = this.object;
    if (object === undefined) return false;
    if (!isValidObject(object, message)) return false;
    addObjectMessage(object, message);
    this.mesh.broadcast(`app.${this.protocol}`, message);
    return true;
  }

  produce(time: number, producer?: string): JsonValue | undefined {
    const chain = this.chain;
    if (chain === undefined) throw new Error('not a transfer node');
    const prod = producer ?? 'alice';
    const block = chain.produce(time, prod);
    if (block !== undefined) this.mesh.broadcast('app.transfer', block);
    return block;
  }

  async connect(addr: string): Promise<void> {
    await this.mesh.connect(addr);
  }

  close(): void {
    this.mesh.close();
  }
}

function meshForTransfer(
  chain: TransferChain,
  listen: string,
  peers: JsonValue,
  udp: boolean,
): Promise<{ mesh: Mesh; listenAddr: string }> {
  const mesh = new Mesh();
  mesh.onApp = (appType, data) => {
    if (appType !== 'app.transfer') return;
    const obj =
      data !== null && typeof data === 'object' && !Array.isArray(data)
        ? (data as Record<string, JsonValue>)
        : undefined;
    if (obj === undefined) return;
    if (obj['chain'] === 'transfer') chain.acceptBlock(data);
    else if (obj['signature'] !== undefined) chain.submit(data);
  };
  const { host, port } = parseListen(listen);
  return mesh.start(host, port).then(async (listenAddr) => {
    if (udp) await mesh.bindUdp();
    if (Array.isArray(peers)) {
      for (const addr of peers) {
        if (typeof addr === 'string' && addr.length > 0) {
          await mesh.connect(addr).catch(() => undefined);
        }
      }
    }
    return { mesh, listenAddr };
  });
}

function meshForObject(
  obj: PresetObject,
  protocol: string,
  listen: string,
  peers: JsonValue,
  udp: boolean,
): Promise<{ mesh: Mesh; listenAddr: string }> {
  const mesh = new Mesh();
  const want = `app.${protocol}`;
  mesh.onApp = (appType, data) => {
    if (appType !== want) return;
    if (isValidObject(obj, data)) addObjectMessage(obj, data);
  };
  const { host, port } = parseListen(listen);
  return mesh.start(host, port).then(async (listenAddr) => {
    if (udp) await mesh.bindUdp();
    if (Array.isArray(peers)) {
      for (const addr of peers) {
        if (typeof addr === 'string' && addr.length > 0) {
          await mesh.connect(addr).catch(() => undefined);
        }
      }
    }
    return { mesh, listenAddr };
  });
}

async function objectHandle(
  obj: PresetObject,
  protocol: string,
  listen: string,
  peers: JsonValue,
  udp: boolean,
): Promise<PresetHandle> {
  const { mesh, listenAddr } = await meshForObject(obj, protocol, listen, peers, udp);
  return new PresetHandle(listenAddr, protocol, mesh, undefined, obj);
}

export async function start(config: JsonValue): Promise<PresetHandle> {
  const map =
    config !== null && typeof config === 'object' && !Array.isArray(config)
      ? (config as Record<string, JsonValue>)
      : undefined;
  if (map === undefined) throw new Error('config must be an object');
  const protocol = map['protocol'];
  if (typeof protocol !== 'string' || !PROTOCOLS.has(protocol)) {
    throw new Error('invalid protocol');
  }
  const listen = typeof map['listen'] === 'string' ? map['listen'] : '127.0.0.1:0';
  const peers = map['peers'] ?? [];
  const udp = jsonBool(map['udp']) ?? false;

  if (protocol === 'transfer') {
    rejectUnknown(
      map,
      new Set(['protocol', 'consensus', 'genesis', 'reward', 'authorities', 'listen', 'peers', 'udp']),
    );
    const consensus = map['consensus'];
    if (typeof consensus !== 'string') throw new Error('consensus required for transfer');
    const genesisVal = map['genesis'];
    if (genesisVal === undefined) throw new Error('genesis required');
    const genesis = jsonI64Map(genesisVal);
    const reward =
      typeof map['reward'] === 'number' && Number.isSafeInteger(map['reward']) ? map['reward'] : 0;
    const opts: JsonValue = {};
    if (consensus === 'poa') {
      const authorities = map['authorities'];
      if (!Array.isArray(authorities) || authorities.length === 0) {
        throw new Error('authorities required for poa');
      }
      (opts as Record<string, JsonValue>)['authorities'] = authorities;
    }
    const driver = makeDriver(consensus, opts);
    const chain = new TransferChain(genesis, reward, driver);
    const { mesh, listenAddr } = await meshForTransfer(chain, listen, peers, udp);
    return new PresetHandle(listenAddr, protocol, mesh, chain);
  }

  if (protocol === 'balance') {
    rejectUnknown(map, new Set(['protocol', 'genesis', 'listen', 'peers', 'udp']));
    const genesis = map['genesis'] === undefined ? { ...BALANCE_DEFAULT } : jsonI64Map(map['genesis']);
    return objectHandle(new BalanceLedger(genesis), protocol, listen, peers, udp);
  }

  if (protocol === 'utxo') {
    rejectUnknown(map, new Set(['protocol', 'genesis', 'listen', 'peers', 'udp']));
    const genesis = map['genesis'] === undefined ? { ...UTXO_DEFAULT } : jsonI64Map(map['genesis']);
    return objectHandle(new UtxoLedger(genesis), protocol, listen, peers, udp);
  }

  if (protocol === 'crdt') {
    rejectUnknown(map, new Set(['protocol', 'listen', 'peers', 'udp']));
    return objectHandle(new CrdtKv(), protocol, listen, peers, udp);
  }

  if (protocol === 'pubsub') {
    rejectUnknown(map, new Set(['protocol', 'listen', 'peers', 'udp']));
    return objectHandle(new PubSub(), protocol, listen, peers, udp);
  }

  validateConsensusConfig(protocol, map);
  return objectHandle(consensusObject(protocol, map), protocol, listen, peers, udp);
}