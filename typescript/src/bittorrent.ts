/** Pedagogical BitTorrent swarm — SPEC/features/bittorrent-swarm.md. */

import { sha256 } from '@noble/hashes/sha2.js';
import {
  type JsonValue,
  bytesToHex,
  compareCodePoints,
  hexToBytes,
} from './canonical.ts';
import { StateMemento } from './memento.ts';
import { BaseSharedObject, merkleDigest } from './object.ts';

export const WIRE_TYPE = 'app.bittorrent';
export const MAX_TORRENTS = 8;
export const MAX_PIECES = 64;
export const MAX_PIECE_BYTES = 65536;
export const MAX_NAME_LEN = 64;
export const MAX_PEER_ID_LEN = 64;
export const MAX_HAVE_PEERS = 32;
export const MAX_SEED_BYTES = MAX_PIECES * MAX_PIECE_BYTES;

const HEX64 = /^[0-9a-f]{64}$/;
const HEX = /^(?:[0-9a-f]{2})+$/;

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message as Record<string, JsonValue>;
}

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

export function pieceHash(data: Uint8Array): string {
  return bytesToHex(sha256(data));
}

export function infoHash(name: string, pieces: readonly string[]): string {
  return merkleDigest({ name, pieces: [...pieces] });
}

export function splitPayload(
  name: string,
  text: string,
  pieceSize: number,
): { infoHash: string; length: number; payloads: string[]; pieces: string[] } {
  if (!name || !text || pieceSize < 1) {
    throw new RangeError('name and data must be non-empty; piece_size >= 1');
  }
  if (name.length > MAX_NAME_LEN || pieceSize > MAX_PIECE_BYTES) {
    throw new RangeError('name or piece_size exceeds the prototype limit');
  }
  const raw = new TextEncoder().encode(text);
  if (raw.length > MAX_SEED_BYTES) {
    throw new RangeError('payload exceeds the prototype limit');
  }
  if (Math.ceil(raw.length / pieceSize) > MAX_PIECES) {
    throw new RangeError('too many pieces');
  }
  const chunks: Uint8Array[] = [];
  for (let i = 0; i < raw.length; i += pieceSize) chunks.push(raw.subarray(i, i + pieceSize));
  const pieces = chunks.map((chunk) => pieceHash(chunk));
  const payloads = chunks.map((chunk) => bytesToHex(chunk));
  return { infoHash: infoHash(name, pieces), length: raw.length, payloads, pieces };
}

interface Torrent {
  name: string;
  pieces: string[];
  data: Map<number, string>;
  have: Map<string, Set<number>>;
}

type Parsed =
  | { kind: 'metainfo'; name: string; pieces: string[]; digest: string }
  | { kind: 'have' | 'request'; digest: string; peer: string; index: number }
  | { kind: 'piece'; digest: string; peer: string; index: number; data: string };

export class Swarm extends BaseSharedObject {
  private readonly torrents = new Map<string, Torrent>();

  override isValid(message: JsonValue): boolean {
    return this.parse(message) !== undefined;
  }

  override addMessage(
    message: JsonValue,
    _frontierState?: StateMemento | undefined,
  ): StateMemento | undefined {
    const parsed = this.parse(message);
    if (parsed === undefined) return this.emitStateMemento();
    if (parsed.kind === 'metainfo') {
      if (!this.torrents.has(parsed.digest)) {
        this.torrents.set(parsed.digest, {
          name: parsed.name,
          pieces: parsed.pieces,
          data: new Map(),
          have: new Map(),
        });
      }
    } else if (parsed.kind === 'have') {
      this.mark(parsed.digest, parsed.peer, parsed.index);
    } else if (parsed.kind === 'piece') {
      const torrent = this.torrents.get(parsed.digest);
      if (torrent !== undefined) {
        torrent.data.set(parsed.index, parsed.data);
        this.mark(parsed.digest, parsed.peer, parsed.index);
      }
    }
    return this.emitStateMemento();
  }

  override emitStateMemento(): StateMemento {
    return StateMemento.normalize(merkleDigest({ torrents: this.snapshot(), v: 1 }), []);
  }

  override getStateDigests(): string[] {
    const digest = this.emitStateMemento().canonicalDigest;
    return digest ? [digest] : [];
  }

  override isMerkelized(): boolean {
    return true;
  }

  state(): { torrents: Record<string, JsonValue>; v: number } {
    return { torrents: this.snapshot(), v: 1 };
  }

  assembled(digest: string): string | null {
    const torrent = this.torrents.get(digest);
    if (torrent === undefined) return null;
    const parts: Uint8Array[] = [];
    for (let index = 0; index < torrent.pieces.length; index += 1) {
      const hex = torrent.data.get(index);
      if (hex === undefined) return null;
      parts.push(hexToBytes(hex));
    }
    const joined = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
    let offset = 0;
    for (const part of parts) {
      joined.set(part, offset);
      offset += part.length;
    }
    return bytesToHex(joined);
  }

  missing(digest: string): number[] {
    const torrent = this.torrents.get(digest);
    if (torrent === undefined) return [];
    const out: number[] = [];
    for (let index = 0; index < torrent.pieces.length; index += 1) {
      if (!torrent.data.has(index)) out.push(index);
    }
    return out;
  }

  pieceHex(digest: string, index: number): string | undefined {
    return this.torrents.get(digest)?.data.get(index);
  }

  known(): string[] {
    return [...this.torrents.keys()].sort(compareCodePoints);
  }

  private mark(digest: string, peer: string, index: number): void {
    const torrent = this.torrents.get(digest);
    if (torrent === undefined) return;
    let set = torrent.have.get(peer);
    if (set === undefined) {
      set = new Set();
      torrent.have.set(peer, set);
    }
    set.add(index);
  }

  private snapshot(): Record<string, JsonValue> {
    const out: Record<string, JsonValue> = {};
    for (const digest of [...this.torrents.keys()].sort(compareCodePoints)) {
      const torrent = this.torrents.get(digest)!;
      const count = torrent.pieces.length;
      const peers = [...torrent.have.keys()].sort(compareCodePoints);
      const have: Record<string, number[]> = {};
      for (const peer of peers) have[peer] = [...torrent.have.get(peer)!].sort((a, b) => a - b);
      const complete = peers.filter((peer) => have[peer]!.length === count && have[peer]!.every((v, i) => v === i));
      const data: Record<string, string> = {};
      for (const index of [...torrent.data.keys()].sort((a, b) => a - b)) {
        data[String(index)] = torrent.data.get(index)!;
      }
      out[digest] = {
        complete,
        data,
        have,
        name: torrent.name,
        pieces: [...torrent.pieces],
      };
    }
    return out;
  }

  private parse(message: JsonValue): Parsed | undefined {
    const record = asRecord(message);
    if (record === undefined) return undefined;
    const kind = record['bt'];
    if (kind === 'metainfo') {
      const name = record['name'];
      const pieces = record['pieces'];
      if (typeof name !== 'string' || !name || name.length > MAX_NAME_LEN) return undefined;
      if (!Array.isArray(pieces) || pieces.length === 0 || pieces.length > MAX_PIECES) {
        return undefined;
      }
      if (!pieces.every((item) => typeof item === 'string' && HEX64.test(item))) return undefined;
      const list = pieces as string[];
      const digest = infoHash(name, list);
      const existing = this.torrents.get(digest);
      if (existing !== undefined && (existing.name !== name || !sameList(existing.pieces, list))) {
        return undefined;
      }
      if (existing === undefined && this.torrents.size >= MAX_TORRENTS) return undefined;
      return { kind: 'metainfo', name, pieces: list, digest };
    }
    if (kind === 'have' || kind === 'piece' || kind === 'request') {
      const digest = record['info_hash'];
      const peer = record['peer'];
      const index = record['index'];
      if (typeof digest !== 'string' || !HEX64.test(digest) || typeof peer !== 'string' || !peer) {
        return undefined;
      }
      if (peer.length > MAX_PEER_ID_LEN) return undefined;
      const torrent = this.torrents.get(digest);
      if (torrent === undefined || !isInt(index) || index < 0 || index >= torrent.pieces.length) {
        return undefined;
      }
      if (kind !== 'request' && !torrent.have.has(peer) && torrent.have.size >= MAX_HAVE_PEERS) {
        return undefined;
      }
      if (kind !== 'piece') return { kind, digest, peer, index };
      const data = record['data'];
      if (typeof data !== 'string' || data.length > MAX_PIECE_BYTES * 2 || !HEX.test(data)) {
        return undefined;
      }
      if (pieceHash(hexToBytes(data)) !== torrent.pieces[index]) return undefined;
      return { kind: 'piece', digest, peer, index, data };
    }
    return undefined;
  }
}

function sameList(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

export class BitTorrentClient {
  readonly swarm = new Swarm();
  localPeer = '';
  readonly broadcast: (typeName: string, data: JsonValue) => string;

  constructor(broadcast: (typeName: string, data: JsonValue) => string) {
    this.broadcast = broadcast;
  }

  onApp(typeName: string, data: JsonValue): void {
    if (typeName !== WIRE_TYPE) return;
    if (this.swarm.isValid(data)) this.swarm.addMessage(data);
    this.serveRequest(data);
  }

  handleCommand(cmd: Record<string, unknown>): Record<string, unknown> | undefined {
    if (cmd['cmd'] === 'bt.seed') {
      return this.seed(String(cmd['peer']), String(cmd['name']), cmd['data'], cmd['piece_size']);
    }
    if (cmd['cmd'] === 'bt.leech') {
      return this.leech(String(cmd['peer']), cmd['info_hash']);
    }
    if (cmd['cmd'] === 'bt.status') return this.status();
    return undefined;
  }

  seed(peer: string, name: string, data: unknown, pieceSize: unknown): Record<string, unknown> {
    if (peer.length > MAX_PEER_ID_LEN || name.length > MAX_NAME_LEN) {
      throw new RangeError('peer or name exceeds the prototype limit');
    }
    if (typeof data !== 'string' || typeof pieceSize !== 'number' || !Number.isSafeInteger(pieceSize)) {
      throw new RangeError('invalid seed');
    }
    this.localPeer = peer;
    const split = splitPayload(name, data, pieceSize);
    this.broadcast(WIRE_TYPE, { bt: 'metainfo', name, pieces: split.pieces });
    split.payloads.forEach((payload, index) => {
      this.broadcast(WIRE_TYPE, {
        bt: 'piece',
        data: payload,
        index,
        info_hash: split.infoHash,
        peer,
      });
    });
    return {
      event: 'bt.seeded',
      info_hash: split.infoHash,
      length: split.length,
      pieces: split.pieces.length,
    };
  }

  leech(peer: string, infoHashValue: unknown): Record<string, unknown> {
    if (peer.length > MAX_PEER_ID_LEN) throw new RangeError('peer exceeds the prototype limit');
    this.localPeer = peer;
    const known = this.swarm.known();
    const digest = typeof infoHashValue === 'string' ? infoHashValue : known[0] ?? '';
    const requested: number[] = [];
    if (digest) {
      for (const index of this.swarm.missing(digest)) {
        this.broadcast(WIRE_TYPE, { bt: 'request', index, info_hash: digest, peer });
        requested.push(index);
      }
    }
    return { event: 'bt.leech', info_hash: digest, requested };
  }

  status(): Record<string, unknown> {
    const snap = this.swarm.state().torrents;
    const torrents = this.swarm.known().map((digest) => {
      const entry = snap[digest] as Record<string, JsonValue>;
      return {
        assembled: this.swarm.assembled(digest),
        complete: entry['complete'],
        have: entry['have'],
        info_hash: digest,
        name: entry['name'],
      };
    });
    return { event: 'bt.status', torrents };
  }

  private serveRequest(data: JsonValue): void {
    if (data === null || typeof data !== 'object' || Array.isArray(data) || !this.localPeer) return;
    const record = data as Record<string, JsonValue>;
    if (record['bt'] !== 'request') return;
    const digest = record['info_hash'];
    const index = record['index'];
    if (typeof digest !== 'string' || typeof index !== 'number') return;
    const payload = this.swarm.pieceHex(digest, index);
    if (payload === undefined) return;
    this.broadcast(WIRE_TYPE, {
      bt: 'piece',
      data: payload,
      index,
      info_hash: digest,
      peer: this.localPeer,
    });
  }
}
