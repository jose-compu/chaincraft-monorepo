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

export {
  Avalanche,
  DEFAULT_ALPHA as AVALANCHE_DEFAULT_ALPHA,
  DEFAULT_BETA as AVALANCHE_DEFAULT_BETA,
  DEFAULT_K as AVALANCHE_DEFAULT_K,
} from './consensusAvalanche.ts';
export { PBFT, DEFAULT_REPLICAS as PBFT_DEFAULT_REPLICAS } from './consensusPbft.ts';
export { ProofOfStake, DEFAULT_SEED, DEFAULT_VALIDATORS, proposerFor } from './consensusPos.ts';
export { ProofOfAuthority, blockId as poaBlockId, proposerFor as poaProposerFor } from './consensusPoa.ts';
export { ProofOfElapsedTime, ticketId as poetTicketId } from './consensusPoet.ts';
export { ProofOfWork, DEFAULT_DIFFICULTY, blockId, meetsWork } from './consensusPow.ts';
export { BalanceLedger, DEFAULT_ALLOCATIONS as BALANCE_DEFAULT_ALLOCATIONS } from './ledgerBalance.ts';
export { CrdtKv, MAX_KEYS as CRDT_MAX_KEYS, MAX_VALUE as CRDT_MAX_VALUE } from './crdt.ts';
export { PubSub, MAX_MEMBERS, MAX_POSTS, MAX_ROOMS, MAX_TEXT } from './pubsub.ts';
export {
  Stream,
  MAX_BATCH,
  MAX_BROKERS,
  MAX_EVENTS,
  MAX_GROUPS,
  MAX_PARTITIONS,
  MAX_PAYLOAD,
  MAX_PRODUCERS,
  MAX_READ,
  MAX_STREAMS,
} from './stream.ts';
export { UtxoLedger, DEFAULT_ALLOCATIONS as UTXO_DEFAULT_ALLOCATIONS, transactionId } from './ledgerUtxo.ts';
export { Mempool, transactionId as mempoolTransactionId } from './mempool.ts';
export * as fees from './fees.ts';
export { MessageStore, isValidId as isValidStoreId } from './storage.ts';
export {
  type InboxItem,
  type ParsedAddress,
  LoopBus,
  LoopChannel,
  MAX_LOOP_BYTES,
  isConnectAllowed as isChannelConnectAllowed,
  parseAddress,
} from './channel.ts';
export {
  AdapterBus,
  AdapterChannel,
  UdpLink,
  MAX_FORUM_BYTES,
  MAX_MAIL_BYTES,
  MAX_PIPE_BYTES,
  MAX_UDP_PAYLOAD,
  MAX_WEBRTC_BYTES,
} from './adapters.ts';
export { NodeSession } from './cli.ts';
export {
  BitTorrentClient,
  Swarm,
  WIRE_TYPE,
  MAX_NAME_LEN,
  MAX_PEER_ID_LEN,
  infoHash,
  pieceHash,
  splitPayload,
} from './bittorrent.ts';
export { Mesh } from './mesh.ts';
export {
  DEFAULT_PEER_ORIGIN,
  PEER_KEY,
  EnvelopeRelay,
  fetchPeerId,
  isPeerId,
  parsePeerIdBody,
  peerOptions,
  type PeerOptions,
  type RelayItem,
} from './peer.ts';
export { HOP_CAP, LinkMesh, helloCaps, type HybridItem } from './hybrid.ts';
export {
  type CodecResult as NatCodecResult,
  type HandleOut as NatHandle,
  type NatMessage,
  type ParsedBinding,
  type Punch as NatPunch,
  type RelayOut as NatRelay,
  APP_NAT,
  NatTraversal,
  PUNCH_HEX,
  bindingRequest,
  bindingSuccess,
  parseBindingResponse,
} from './nat.ts';
export * as ecdsa from './ecdsa.ts';
export * as vdf from './vdf.ts';
export * as vrf from './vrf.ts';
export {
  AddressBook,
  LocalDiscovery,
  DEFAULT_CAPACITY as DISCOVERY_DEFAULT_CAPACITY,
  DEFAULT_TIMEOUT_MS as DISCOVERY_DEFAULT_TIMEOUT_MS,
  isValidAddress,
  isConnectAllowed,
  isResolvedIpAllowed,
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
