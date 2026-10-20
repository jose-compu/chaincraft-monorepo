/** Node JSON-lines command surface — SPEC/features/cli-node.md. */

import { parseJson, payloadDigest, type JsonValue } from './canonical.ts';
import { CanonicalError } from './errors.ts';
import { parseAddress } from './channel.ts';

const TYPE_RE = /^[a-z0-9._-]{1,64}$/;

export type CliEvent = Record<string, JsonValue>;

function asRecord(value: JsonValue): Record<string, JsonValue> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, JsonValue>;
}

export class NodeSession {
  readonly impl: string;
  readonly listen: string;
  peers: string[];
  ids: string[];
  closed: boolean;

  constructor(impl: string, listen: string) {
    if (!impl || !listen) throw new RangeError('impl and listen must be non-empty');
    this.impl = impl;
    this.listen = listen;
    this.peers = [];
    this.ids = [];
    this.closed = false;
  }

  start(): CliEvent[] {
    return [{ event: 'ready', addr: this.listen, impl: this.impl }];
  }

  handle(line: string): CliEvent[] {
    if (line.trim() === '') return [];
    if (this.closed) return [error('closed')];
    let command: JsonValue;
    try {
      command = parseJson(line);
    } catch (err) {
      if (err instanceof CanonicalError) return [error('invalid json')];
      throw err;
    }
    const record = asRecord(command);
    if (record === undefined) return [error('invalid json')];
    const name = record['cmd'];
    if (name === 'connect') return this.connect(record);
    if (name === 'send') return this.send(record);
    if (name === 'ids') return [{ event: 'ids', ids: [...this.ids] }];
    if (name === 'quit') {
      this.closed = true;
      return [{ event: 'quit' }];
    }
    return [error('unknown cmd')];
  }

  state(): { closed: boolean; ids: string[]; peers: string[] } {
    return { closed: this.closed, ids: [...this.ids], peers: [...this.peers] };
  }

  private connect(command: Record<string, JsonValue>): CliEvent[] {
    const addr = command['addr'];
    if (typeof addr !== 'string' || !parseAddress(addr).ok) return [error('invalid address')];
    if (!this.peers.includes(addr)) this.peers.push(addr);
    return [{ event: 'connected', addr }];
  }

  private send(command: Record<string, JsonValue>): CliEvent[] {
    const typeName = command['type'];
    if (typeof typeName !== 'string' || !TYPE_RE.test(typeName)) return [error('invalid send')];
    if (!('data' in command)) return [error('invalid send')];
    try {
      const digest = payloadDigest(command['data'] as JsonValue);
      this.ids.push(digest);
      return [{ event: 'sent', id: digest }];
    } catch (err) {
      if (err instanceof CanonicalError) return [error('invalid send')];
      throw err;
    }
  }
}

function error(message: string): CliEvent {
  return { event: 'error', message };
}
