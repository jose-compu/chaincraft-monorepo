/** Append-only event log — SPEC/features/app-stream.md. */

import { type JsonValue, MAX_SAFE_INT, compareCodePoints } from './canonical.ts';
import { BaseSharedObject } from './object.ts';

export const MAX_STREAMS = 32;
export const MAX_PARTITIONS = 16;
export const MAX_PRODUCERS = 32;
export const MAX_EVENTS = 64;
export const MAX_GROUPS = 32;
export const MAX_BROKERS = 8;
export const MAX_BATCH = 64;
export const MAX_PAYLOAD = 4096;
export const MAX_READ = 256;

const NAME = /^[A-Za-z0-9._-]{1,64}$/;

export interface StreamEvent {
  producer: string;
  seq: number;
  payload: string;
}

interface LogRecord {
  producer: string;
  seq: number;
  payload: string;
}

interface Partition {
  producers: Set<string>;
  events: Map<string, StreamEvent>;
  groups: Map<string, Map<string, number>>;
  trimmed: Map<string, number>;
}

interface Log {
  retention: number;
  brokers: Map<string, boolean>;
  partitions: Map<number, Partition>;
}

type Op =
  | { op: 'open'; stream: string; partition: number; producer: string }
  | { op: 'write'; stream: string; partition: number; records: LogRecord[] }
  | { op: 'commit'; stream: string; partition: number; group: string; producer: string; seq: number }
  | { op: 'join'; stream: string; broker: string }
  | { op: 'fail'; stream: string; broker: string }
  | { op: 'retain'; stream: string; keep: number };

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message;
}

function eventKey(producer: string, seq: number): string {
  return `${producer}\0${seq}`;
}

function newPartition(): Partition {
  return { producers: new Set(), events: new Map(), groups: new Map(), trimmed: new Map() };
}

function newLog(): Log {
  return { retention: MAX_EVENTS, brokers: new Map(), partitions: new Map() };
}

function available(log: Log): boolean {
  if (log.brokers.size === 0) return true;
  for (const up of log.brokers.values()) {
    if (up) return true;
  }
  return false;
}

function dropOldest(events: Map<string, StreamEvent>, trimmed: Map<string, number>): void {
  let oldest: StreamEvent | undefined;
  for (const event of events.values()) {
    if (
      oldest === undefined ||
      event.seq < oldest.seq ||
      (event.seq === oldest.seq && compareCodePoints(event.producer, oldest.producer) < 0)
    ) {
      oldest = event;
    }
  }
  if (oldest === undefined) return;
  events.delete(eventKey(oldest.producer, oldest.seq));
  const mark = trimmed.get(oldest.producer) ?? -1;
  if (oldest.seq === mark + 1) trimmed.set(oldest.producer, oldest.seq);
}

function trimTo(events: Map<string, StreamEvent>, trimmed: Map<string, number>, keep: number): void {
  while (events.size > keep) dropOldest(events, trimmed);
}

function mutateRecords(
  events: Map<string, StreamEvent>,
  trimmed: Map<string, number>,
  producers: Set<string>,
  retention: number,
  records: LogRecord[],
): boolean {
  for (const record of records) {
    if (!producers.has(record.producer)) return false;
    const mark = trimmed.get(record.producer) ?? -1;
    if (record.seq <= mark) return false;
    const key = eventKey(record.producer, record.seq);
    const prior = events.get(key);
    if (prior !== undefined) {
      if (prior.payload !== record.payload) return false;
      continue;
    }
    if (events.size >= MAX_EVENTS) return false;
    events.set(key, record);
    trimTo(events, trimmed, retention);
  }
  return true;
}

function prefixClosed(
  events: Map<string, StreamEvent>,
  trimmed: Map<string, number>,
  producer: string,
  seq: number,
): boolean {
  // Count stored records. Walking mark+1..=seq hangs on a large sparse seq.
  if (!events.has(eventKey(producer, seq))) return false;
  const mark = trimmed.get(producer) ?? -1;
  if (seq <= mark) return false;
  let found = 0;
  for (const event of events.values()) {
    if (event.producer === producer && event.seq > mark && event.seq <= seq) found += 1;
  }
  return found === seq - mark;
}

function copyEvents(events: Map<string, StreamEvent>): Map<string, StreamEvent> {
  return new Map(events);
}

function byEvent(a: StreamEvent, b: StreamEvent): number {
  if (a.seq < b.seq) return -1;
  if (a.seq > b.seq) return 1;
  return compareCodePoints(a.producer, b.producer);
}

export class Stream extends BaseSharedObject {
  private readonly streams = new Map<string, Log>();

  override isValid(message: JsonValue): boolean {
    return this.parse(message) !== undefined;
  }

  override receive(message: JsonValue): void {
    const parsed = this.parse(message);
    if (parsed === undefined) return;
    if (parsed.op === 'open') {
      let log = this.streams.get(parsed.stream);
      if (log === undefined) {
        log = newLog();
        this.streams.set(parsed.stream, log);
      }
      let part = log.partitions.get(parsed.partition);
      if (part === undefined) {
        part = newPartition();
        log.partitions.set(parsed.partition, part);
      }
      part.producers.add(parsed.producer);
    } else if (parsed.op === 'write') {
      const log = this.streams.get(parsed.stream);
      const part = log?.partitions.get(parsed.partition);
      if (log === undefined || part === undefined) return;
      const events = copyEvents(part.events);
      const trimmed = new Map(part.trimmed);
      mutateRecords(events, trimmed, part.producers, log.retention, parsed.records);
      part.events = events;
      part.trimmed = trimmed;
    } else if (parsed.op === 'commit') {
      const part = this.streams.get(parsed.stream)?.partitions.get(parsed.partition);
      if (part === undefined) return;
      let cursors = part.groups.get(parsed.group);
      if (cursors === undefined) {
        cursors = new Map();
        part.groups.set(parsed.group, cursors);
      }
      const current = cursors.get(parsed.producer);
      if (current === undefined || parsed.seq > current) cursors.set(parsed.producer, parsed.seq);
    } else if (parsed.op === 'join') {
      let log = this.streams.get(parsed.stream);
      if (log === undefined) {
        log = newLog();
        this.streams.set(parsed.stream, log);
      }
      log.brokers.set(parsed.broker, true);
    } else if (parsed.op === 'fail') {
      this.streams.get(parsed.stream)?.brokers.set(parsed.broker, false);
    } else {
      const log = this.streams.get(parsed.stream);
      if (log === undefined) return;
      log.retention = parsed.keep;
      for (const part of log.partitions.values()) {
        trimTo(part.events, part.trimmed, parsed.keep);
      }
    }
  }

  state(): {
    streams: Array<{
      name: string;
      retention: number;
      replicas: Array<{ broker: string; status: 'up' | 'down' }>;
      partitions: Array<{
        partition: number;
        producers: string[];
        events: StreamEvent[];
        groups: Array<{ name: string; cursors: Array<{ producer: string; seq: number }> }>;
        trimmed: Array<{ producer: string; seq: number }>;
      }>;
    }>;
  } {
    const names = Array.from(this.streams.keys()).sort(compareCodePoints);
    return {
      streams: names.map((name) => {
        const log = this.streams.get(name)!;
        const pids = Array.from(log.partitions.keys()).sort((a, b) => a - b);
        const partitions = pids.map((pid) => {
          const part = log.partitions.get(pid)!;
          const producers = Array.from(part.producers).sort(compareCodePoints);
          const events = Array.from(part.events.values()).sort(byEvent);
          const groupNames = Array.from(part.groups.keys()).sort(compareCodePoints);
          const groups = groupNames.map((groupName) => {
            const cursors = part.groups.get(groupName)!;
            const rows = Array.from(cursors.entries())
              .sort((a, b) => compareCodePoints(a[0], b[0]))
              .map(([producer, seq]) => ({ producer, seq }));
            return { name: groupName, cursors: rows };
          });
          const trimmed = Array.from(part.trimmed.entries())
            .sort((a, b) => compareCodePoints(a[0], b[0]))
            .map(([producer, seq]) => ({ producer, seq }));
          return { partition: pid, producers, events, groups, trimmed };
        });
        const replicas = Array.from(log.brokers.entries())
          .sort((a, b) => compareCodePoints(a[0], b[0]))
          .map(([broker, up]) => ({ broker, status: up ? ('up' as const) : ('down' as const) }));
        return { name, retention: log.retention, replicas, partitions };
      }),
    };
  }

  read(stream: JsonValue, partition: JsonValue, after: JsonValue, limit: JsonValue): StreamEvent[] {
    if (typeof stream !== 'string') return [];
    if (!isInt(partition) || partition < 0 || partition >= MAX_PARTITIONS) return [];
    if (!isInt(limit) || limit < 1 || limit > MAX_READ) return [];
    const log = this.streams.get(stream);
    if (log === undefined || !available(log)) return [];
    const part = log.partitions.get(partition);
    if (part === undefined) return [];
    const cursor = this.cursor(after);
    if (cursor === false) return [];
    const events = Array.from(part.events.values()).sort(byEvent);
    const selected =
      cursor === null
        ? events
        : events.filter(
            (event) =>
              event.seq > cursor.seq ||
              (event.seq === cursor.seq && compareCodePoints(event.producer, cursor.producer) > 0),
          );
    return selected.slice(0, limit);
  }

  private cursor(after: JsonValue): { producer: string; seq: number } | null | false {
    if (after === null) return null;
    const obj = asRecord(after);
    if (obj === undefined) return false;
    const producer = obj['producer'];
    const seq = obj['seq'];
    if (typeof producer !== 'string' || !NAME.test(producer)) return false;
    if (!isInt(seq) || seq < 0 || seq > MAX_SAFE_INT) return false;
    return { producer, seq };
  }

  private parse(message: JsonValue): Op | undefined {
    const obj = asRecord(message);
    if (obj === undefined || obj['app'] !== 'stream') return undefined;
    const op = obj['op'];
    const stream = obj['stream'];
    if (typeof stream !== 'string' || !NAME.test(stream)) return undefined;
    if (op === 'open' || op === 'produce' || op === 'append' || op === 'commit') {
      const partition = partitionId(obj);
      if (partition === undefined) return undefined;
      return this.parseData(obj, op, stream, partition);
    }
    if (op === 'join') return this.parseJoin(stream, obj['broker']);
    if (op === 'fail') return this.parseFail(stream, obj['broker']);
    if (op === 'retain') return this.parseRetain(stream, obj['keep']);
    return undefined;
  }

  private parseData(
    obj: Record<string, JsonValue>,
    op: 'open' | 'produce' | 'append' | 'commit',
    stream: string,
    partition: number,
  ): Op | undefined {
    const log = this.streams.get(stream);
    if (log !== undefined && !available(log)) return undefined;
    if (op === 'open') {
      const producer = obj['producer'];
      if (typeof producer !== 'string' || !NAME.test(producer)) return undefined;
      if (log === undefined && this.streams.size >= MAX_STREAMS) return undefined;
      const part = log?.partitions.get(partition);
      if (log !== undefined && part === undefined && log.partitions.size >= MAX_PARTITIONS) {
        return undefined;
      }
      if (
        part !== undefined &&
        !part.producers.has(producer) &&
        part.producers.size >= MAX_PRODUCERS
      ) {
        return undefined;
      }
      return { op, stream, partition, producer };
    }
    if (log === undefined) return undefined;
    const part = log.partitions.get(partition);
    if (part === undefined) return undefined;
    if (op === 'commit') {
      const group = obj['group'];
      const producer = obj['producer'];
      const seq = obj['seq'];
      if (typeof group !== 'string' || !NAME.test(group)) return undefined;
      if (typeof producer !== 'string' || !NAME.test(producer)) return undefined;
      if (!isInt(seq) || seq < 0 || seq > MAX_SAFE_INT) return undefined;
      if (!part.producers.has(producer)) return undefined;
      if (!prefixClosed(part.events, part.trimmed, producer, seq)) return undefined;
      if (!part.groups.has(group) && part.groups.size >= MAX_GROUPS) return undefined;
      return { op, stream, partition, group, producer, seq };
    }
    const records = recordsOf(obj, op);
    if (records === undefined) return undefined;
    const events = copyEvents(part.events);
    const trimmed = new Map(part.trimmed);
    if (!mutateRecords(events, trimmed, part.producers, log.retention, records)) return undefined;
    return { op: 'write', stream, partition, records };
  }

  private parseJoin(stream: string, broker: JsonValue | undefined): Op | undefined {
    if (typeof broker !== 'string' || !NAME.test(broker)) return undefined;
    const log = this.streams.get(stream);
    if (log === undefined && this.streams.size >= MAX_STREAMS) return undefined;
    if (log !== undefined && !log.brokers.has(broker) && log.brokers.size >= MAX_BROKERS) {
      return undefined;
    }
    return { op: 'join', stream, broker };
  }

  private parseFail(stream: string, broker: JsonValue | undefined): Op | undefined {
    if (typeof broker !== 'string' || !NAME.test(broker)) return undefined;
    const log = this.streams.get(stream);
    if (log === undefined || !log.brokers.has(broker)) return undefined;
    return { op: 'fail', stream, broker };
  }

  private parseRetain(stream: string, keep: JsonValue | undefined): Op | undefined {
    if (!isInt(keep) || keep < 1 || keep > MAX_EVENTS) return undefined;
    if (!this.streams.has(stream)) return undefined;
    return { op: 'retain', stream, keep };
  }
}

function partitionId(obj: Record<string, JsonValue>): number | undefined {
  if (!Object.prototype.hasOwnProperty.call(obj, 'partition')) return 0;
  const value = obj['partition'];
  if (!isInt(value) || value < 0 || value >= MAX_PARTITIONS) return undefined;
  return value;
}

function oneRecord(
  producer: JsonValue | undefined,
  seq: JsonValue | undefined,
  payload: JsonValue | undefined,
): LogRecord | undefined {
  if (typeof producer !== 'string' || !NAME.test(producer)) return undefined;
  if (typeof payload !== 'string') return undefined;
  const scalars = Array.from(payload).length;
  if (scalars < 1 || scalars > MAX_PAYLOAD) return undefined;
  if (!isInt(seq) || seq < 0 || seq > MAX_SAFE_INT) return undefined;
  return { producer, seq, payload };
}

function recordsOf(
  obj: Record<string, JsonValue>,
  op: 'produce' | 'append',
): LogRecord[] | undefined {
  if (op === 'produce') {
    const record = oneRecord(obj['producer'], obj['seq'], obj['payload']);
    return record === undefined ? undefined : [record];
  }
  const raw = obj['records'];
  if (!Array.isArray(raw) || raw.length < 1 || raw.length > MAX_BATCH) return undefined;
  const records: LogRecord[] = [];
  for (const item of raw) {
    const rec = asRecord(item);
    if (rec === undefined) return undefined;
    const record = oneRecord(rec['producer'], rec['seq'], rec['payload']);
    if (record === undefined) return undefined;
    records.push(record);
  }
  return records;
}
