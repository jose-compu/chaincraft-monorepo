/**
 * Feature manifest — the IDs this implementation claims to provide.
 *
 * Cross-checked against SPEC/features.yaml by tools/parity_check.py. A registry
 * entry claiming a feature absent from this list is a hard CI failure, which is
 * what keeps the registry from drifting into fiction.
 *
 * Add an ID here only when the feature is implemented and its vectors pass.
 */

export const VERSION = '1.0.0';
export const WIRE_VERSION = 1;
export const IMPL = `ts-chaincraft/${VERSION}`;
export const LANGUAGE = 'typescript';

export const FEATURES: readonly string[] = [
  // Level 0 — wire protocol.
  // wire.framing-udp is exempt for TypeScript: browsers have no raw UDP
  // sockets, and UDP is optional at Level 0. See SPEC/features.yaml.
  'wire.canonical-json',
  'wire.payload-digest',
  'wire.envelope',
  'wire.framing-tcp',
  'wire.control',
  'wire.version-negotiation',
  'wire.sig-schnorr',
  'wire.sig-ed25519',
  'wire.dedup',
  'wire.paths',
  // Level 1 — object semantics
  'object.contract',
  'object.pipeline',
  'object.memento',
  'object.merkle-digest',
  'object.tiebreak',
  // Level 2 — crypto
  'crypto.ecdsa',
  'crypto.vdf',
  'crypto.vrf',
  'discovery.peer',
  'discovery.local',
  'discovery.nat',
  'consensus.pow',
  'consensus.pos',
  'consensus.pbft',
  'ledger.balance',
  'ledger.utxo',
  'mempool.basic',
  'fees.policy',
  'storage.persistent',
  'cli.node',
  'bittorrent.swarm',
  'wire.channel',
  'channel.udp',
  'channel.mailto',
  'channel.webrtc',
  'channel.forum',
  'app.pubsub',
];

export interface Manifest {
  readonly impl: string;
  readonly language: string;
  readonly version: string;
  readonly wire_version: number;
  readonly features: string[];
}

export function manifest(): Manifest {
  return {
    impl: IMPL,
    language: LANGUAGE,
    version: VERSION,
    wire_version: WIRE_VERSION,
    features: [...FEATURES].sort(),
  };
}
