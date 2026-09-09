/**
 * Framing and transport — SPEC/wire-v1.md §4.
 *
 *     [u32 big-endian length][canonical JSON body]
 */

import { FramingError } from './errors.ts';

export const MAX_FRAME_BYTES = 16777216; // 16 MiB
export const MAX_UDP_BYTES = 65507;

/** Prefix a body with its big-endian u32 length — §4.1. */
export function encodeFrame(body: Uint8Array): Uint8Array {
  if (body.length === 0) {
    throw new FramingError('zero-length frame is invalid');
  }
  if (body.length > MAX_FRAME_BYTES) {
    throw new FramingError(
      `frame of ${body.length} bytes exceeds ${MAX_FRAME_BYTES}`,
    );
  }
  const out = new Uint8Array(4 + body.length);
  new DataView(out.buffer).setUint32(0, body.length, false);
  out.set(body, 4);
  return out;
}

/** One envelope per datagram, no length prefix — §4.2. */
export function encodeDatagram(body: Uint8Array): Uint8Array {
  checkDatagram(body.length);
  return body;
}

export function decodeDatagram(data: Uint8Array): Uint8Array {
  checkDatagram(data.length);
  return data;
}

function checkDatagram(length: number): void {
  if (length === 0) {
    throw new FramingError('zero-length datagram is invalid');
  }
  if (length > MAX_UDP_BYTES) {
    throw new FramingError(`datagram of ${length} bytes exceeds ${MAX_UDP_BYTES}`);
  }
}

/**
 * Reassembles frames from an arbitrarily chunked byte stream.
 *
 * A TCP read boundary has nothing to do with a frame boundary, so callers feed
 * whatever arrived and drain whole frames as they complete.
 */
export class FrameReader {
  private buffer = new Uint8Array(0);
  readonly maxFrameBytes: number;

  constructor(maxFrameBytes: number = MAX_FRAME_BYTES) {
    this.maxFrameBytes = maxFrameBytes;
  }

  /** Append a chunk and return every frame that is now complete. */
  feed(chunk: Uint8Array): Uint8Array[] {
    if (chunk.length > 0) {
      const merged = new Uint8Array(this.buffer.length + chunk.length);
      merged.set(this.buffer, 0);
      merged.set(chunk, this.buffer.length);
      this.buffer = merged;
    }

    const frames: Uint8Array[] = [];
    for (;;) {
      if (this.buffer.length < 4) break;
      const view = new DataView(
        this.buffer.buffer,
        this.buffer.byteOffset,
        this.buffer.byteLength,
      );
      const length = view.getUint32(0, false);
      if (length === 0) {
        throw new FramingError('zero-length frame is invalid');
      }
      if (length > this.maxFrameBytes) {
        throw new FramingError(
          `declared length ${length} exceeds ${this.maxFrameBytes}`,
        );
      }
      if (this.buffer.length < 4 + length) break;
      frames.push(this.buffer.slice(4, 4 + length));
      this.buffer = this.buffer.slice(4 + length);
    }
    return frames;
  }

  /** Bytes buffered but not yet forming a complete frame. */
  get pending(): number {
    return this.buffer.length;
  }
}
