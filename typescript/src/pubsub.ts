/** Topic publish-subscribe — SPEC/features/app-pubsub.md. */

import { type JsonValue, MAX_SAFE_INT, compareCodePoints } from './canonical.ts';
import { BaseSharedObject } from './object.ts';

export const MAX_ROOMS = 32;
export const MAX_MEMBERS = 32;
export const MAX_POSTS = 64;
export const MAX_TEXT = 1024;

const NAME = /^[A-Za-z0-9._-]{1,64}$/;

type Post = { author: string; seq: number; text: string };

type Op =
  | { op: 'subscribe'; room: string; author: string }
  | { op: 'unsubscribe'; room: string; author: string }
  | { op: 'publish'; room: string; author: string; text: string; seq: number };

interface Room {
  members: Set<string>;
  posts: Map<string, Post>;
}

function isInt(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function asRecord(message: JsonValue): Record<string, JsonValue> | undefined {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    return undefined;
  }
  return message;
}

function postKey(author: string, seq: number): string {
  return `${author}\0${seq}`;
}

export interface PubSubState {
  rooms: Array<{ name: string; members: string[]; posts: Post[] }>;
}

export class PubSub extends BaseSharedObject {
  private readonly rooms = new Map<string, Room>();

  override isValid(message: JsonValue): boolean {
    return this.parse(message) !== undefined;
  }

  override receive(message: JsonValue): void {
    const parsed = this.parse(message);
    if (parsed === undefined) return;
    if (parsed.op === 'subscribe') {
      let room = this.rooms.get(parsed.room);
      if (room === undefined) {
        room = { members: new Set(), posts: new Map() };
        this.rooms.set(parsed.room, room);
      }
      room.members.add(parsed.author);
    } else if (parsed.op === 'unsubscribe') {
      const room = this.rooms.get(parsed.room);
      if (room !== undefined) {
        room.members.delete(parsed.author);
        if (room.members.size === 0 && room.posts.size === 0) {
          this.rooms.delete(parsed.room);
        }
      }
    } else {
      this.rooms
        .get(parsed.room)
        ?.posts.set(postKey(parsed.author, parsed.seq), {
          author: parsed.author,
          seq: parsed.seq,
          text: parsed.text,
        });
    }
  }

  state(): PubSubState {
    return { rooms: this.roomList() };
  }

  private roomList(): PubSubState['rooms'] {
    const names = Array.from(this.rooms.keys()).sort(compareCodePoints);
    return names.map((name) => {
      const room = this.rooms.get(name)!;
      const members = Array.from(room.members).sort(compareCodePoints);
      const posts = Array.from(room.posts.values()).sort((a, b) => {
        if (a.seq < b.seq) return -1;
        if (a.seq > b.seq) return 1;
        return compareCodePoints(a.author, b.author);
      });
      return { name, members, posts };
    });
  }

  private parse(message: JsonValue): Op | undefined {
    const obj = asRecord(message);
    if (obj === undefined || obj['app'] !== 'pubsub') return undefined;
    const op = obj['op'];
    const room = obj['room'];
    const author = obj['author'];
    if (op !== 'subscribe' && op !== 'unsubscribe' && op !== 'publish') return undefined;
    if (typeof room !== 'string' || !NAME.test(room)) return undefined;
    if (typeof author !== 'string' || !NAME.test(author)) return undefined;
    const existing = this.rooms.get(room);
    if (op === 'subscribe') {
      if (existing === undefined && this.rooms.size >= MAX_ROOMS) return undefined;
      if (
        existing !== undefined &&
        !existing.members.has(author) &&
        existing.members.size >= MAX_MEMBERS
      ) {
        return undefined;
      }
      return { op, room, author };
    }
    if (op === 'unsubscribe') {
      if (existing === undefined || !existing.members.has(author)) return undefined;
      return { op, room, author };
    }
    const text = obj['text'];
    const seq = obj['seq'];
    if (typeof text !== 'string') return undefined;
    const scalars = Array.from(text).length;
    if (scalars < 1 || scalars > MAX_TEXT) return undefined;
    if (!isInt(seq) || seq < 0 || seq > MAX_SAFE_INT) return undefined;
    if (existing === undefined || !existing.members.has(author)) return undefined;
    if (existing.posts.has(postKey(author, seq)) || existing.posts.size >= MAX_POSTS) {
      return undefined;
    }
    return { op: 'publish', room, author, text, seq };
  }
}
