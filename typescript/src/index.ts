/**
 * @chaincraft/core — Level 0 wire protocol and Level 1 object semantics.
 *
 * Implements SPEC/wire-v1.md and SPEC/semantics-v1.md. Consensus, ledgers,
 * storage and the application layer are Level 2 and live in their own modules.
 */

export {
  ChaincraftError,
  CanonicalError,
  ProtocolError,
  FramingError,
} from './errors.ts';

export {
  type JsonValue,
  MAX_DEPTH,
  MAX_SAFE_INT,
  MIN_SAFE_INT,
  bytesToHex,
  canonicalBytes,
  canonicalJson,
  compareCodePoints,
  hexToBytes,
  parseJson,
  payloadDigest,
} from './canonical.ts';

export {
  type BuildOptions,
  type ParseOptions,
  Envelope,
  MAX_FUTURE_SKEW_MS,
  PROTOCOL_VERSION,
} from './envelope.ts';

export {
  FrameReader,
  MAX_FRAME_BYTES,
  MAX_UDP_BYTES,
  decodeDatagram,
  encodeDatagram,
  encodeFrame,
} from './framing.ts';

export {
  type SignResult,
  type SignatureAlgorithm,
  ALGORITHMS,
  ED25519,
  SCHNORR,
  isAlgorithm,
  publicKey,
  publicKeyHex,
  sign,
  verify,
} from './crypto.ts';

export * as control from './control.ts';

export { DEFAULT_CAPACITY, Deduplicator, SeenDigests } from './dedup.ts';

export { type StateMementoObject, StateMemento } from './memento.ts';

export {
  type SharedObject,
  BaseSharedObject,
  FRONTIER_FORMAT_VERSION,
  frontierDigest,
  merkleDigest,
  winsReplacement,
} from './object.ts';

export { type ApplyResult, ObjectRegistry } from './pipeline.ts';

export { PBFT, DEFAULT_REPLICAS as PBFT_DEFAULT_REPLICAS } from './consensusPbft.ts';
export { ProofOfStake, DEFAULT_SEED, DEFAULT_VALIDATORS, proposerFor } from './consensusPos.ts';
export { ProofOfWork, DEFAULT_DIFFICULTY, blockId, meetsWork } from './consensusPow.ts';
export { BalanceLedger, DEFAULT_ALLOCATIONS as BALANCE_DEFAULT_ALLOCATIONS } from './ledgerBalance.ts';
export { UtxoLedger, DEFAULT_ALLOCATIONS as UTXO_DEFAULT_ALLOCATIONS, transactionId } from './ledgerUtxo.ts';
export * as ecdsa from './ecdsa.ts';
export * as vdf from './vdf.ts';
export * as vrf from './vrf.ts';
export {
  AddressBook,
  LocalDiscovery,
  DEFAULT_CAPACITY as DISCOVERY_DEFAULT_CAPACITY,
  DEFAULT_TIMEOUT_MS as DISCOVERY_DEFAULT_TIMEOUT_MS,
  isValidAddress,
} from './discovery.ts';

export {
  type Manifest,
  FEATURES,
  IMPL,
  LANGUAGE,
  VERSION,
  WIRE_VERSION,
  manifest,
} from './features.ts';
