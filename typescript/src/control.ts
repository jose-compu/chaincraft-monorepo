/** Control messages — SPEC/wire-v1.md §5. */

import { type JsonValue, compareCodePoints } from './canonical.ts';
import { Envelope, PROTOCOL_VERSION } from './envelope.ts';
import { ProtocolError } from './errors.ts';

export const HELLO = 'ctl.hello';
export const PEERS_REQUEST = 'ctl.peers.request';
export const PEERS = 'ctl.peers';
export const DIGEST_REQUEST = 'ctl.digest.request';
export const DIGEST = 'ctl.digest';
export const MESSAGES_REQUEST = 'ctl.messages.request';
export const MESSAGES = 'ctl.messages';

export const CONTROL_TYPES: ReadonlySet<string> = new Set([
  HELLO,
  PEERS_REQUEST,
  PEERS,
  DIGEST_REQUEST,
  DIGEST,
  MESSAGES_REQUEST,
  MESSAGES,
]);

export const CAP_GOSSIP = 'gossip';
export const CAP_DIGEST_SYNC = 'digest-sync';
export const CAP_UDP = 'udp';

export const CAPABILITIES: ReadonlySet<string> = new Set([
  CAP_GOSSIP,
  CAP_DIGEST_SYNC,
  CAP_UDP,
]);

export interface HelloData {
  readonly v: number;
  readonly impl: string;
  readonly caps: readonly string[];
  readonly unknownCaps: readonly string[];
  readonly listen: string | undefined;
}

interface WithTs {
  readonly ts?: number;
}

function build(type: string, data: JsonValue, options: WithTs): Envelope {
  return options.ts === undefined
    ? Envelope.build(type, data)
    : Envelope.build(type, data, { ts: options.ts });
}

/**
 * §5.1. `caps` is sorted and deduplicated: the digest is the message identity,
 * so an identical capability set must serialize identically.
 */
export function hello(
  impl: string,
  options: WithTs & {
    readonly caps?: readonly string[];
    readonly listen?: string;
  } = {},
): Envelope {
  const caps = Array.from(new Set(options.caps ?? [CAP_GOSSIP, CAP_DIGEST_SYNC])).sort(
    compareCodePoints,
  );
  const data: Record<string, JsonValue> = {
    v: PROTOCOL_VERSION,
    impl,
    caps,
  };
  if (options.listen !== undefined) {
    data['listen'] = options.listen;
  }
  return build(HELLO, data, options);
}

/**
 * Validate a ctl.hello payload.
 *
 * Throws on a version we cannot serve so the caller can disconnect cleanly, as
 * §5.1 requires, rather than failing later somewhere less obvious.
 */
export function parseHello(env: Envelope): HelloData {
  if (env.type !== HELLO) {
    throw new ProtocolError(`expected ${HELLO}, got ${env.type}`);
  }
  const data = env.data;
  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    throw new ProtocolError('ctl.hello data must be an object');
  }
  const obj = data as Record<string, JsonValue>;

  const version = obj['v'];
  if (typeof version !== 'number' || !Number.isSafeInteger(version)) {
    throw new ProtocolError('ctl.hello requires an integer v');
  }
  if (version !== PROTOCOL_VERSION) {
    throw new ProtocolError(
      `peer speaks protocol v${version}, we speak v${PROTOCOL_VERSION}`,
    );
  }

  const impl = obj['impl'];
  if (typeof impl !== 'string' || impl.length === 0) {
    throw new ProtocolError('ctl.hello requires impl');
  }

  const caps = obj['caps'];
  if (!Array.isArray(caps) || !caps.every((cap) => typeof cap === 'string')) {
    throw new ProtocolError('ctl.hello requires caps as an array of strings');
  }
  const capList = caps as string[];

  const listen = obj['listen'];
  if (listen !== undefined && typeof listen !== 'string') {
    throw new ProtocolError('ctl.hello listen must be a string');
  }

  // Unknown capabilities are ignored rather than rejected, which is what keeps
  // us forward compatible with a peer newer than us.
  return {
    v: version,
    impl,
    caps: capList.filter((cap) => CAPABILITIES.has(cap)),
    unknownCaps: capList.filter((cap) => !CAPABILITIES.has(cap)),
    listen: typeof listen === 'string' ? listen : undefined,
  };
}

export function peersRequest(options: WithTs = {}): Envelope {
  return build(PEERS_REQUEST, {}, options);
}

export function peers(addresses: readonly string[], options: WithTs = {}): Envelope {
  return build(PEERS, { peers: [...addresses] }, options);
}

export function digestRequest(objectName: string, options: WithTs = {}): Envelope {
  return build(DIGEST_REQUEST, { object: objectName }, options);
}

export function digest(
  objectName: string,
  digestHex: string,
  frontier: readonly string[] = [],
  options: WithTs = {},
): Envelope {
  return build(
    DIGEST,
    { object: objectName, digest: digestHex, frontier: [...frontier] },
    options,
  );
}

export function messagesRequest(
  objectName: string,
  since: string,
  options: WithTs = {},
): Envelope {
  return build(MESSAGES_REQUEST, { object: objectName, since }, options);
}

export function messages(
  objectName: string,
  envelopes: readonly Envelope[],
  options: WithTs = {},
): Envelope {
  return build(
    MESSAGES,
    { object: objectName, messages: envelopes.map((env) => env.toObject()) },
    options,
  );
}
