/**
 * Browser entry for @chaincraft/core.
 *
 * No TCP mesh and no UDP socket. PeerJS options default to the public
 * broker at DEFAULT_PEER_ORIGIN. Opening the data channel is the caller's
 * `new Peer(id, peerOptions())`.
 */

export { Envelope } from './envelope.ts';
export { BaseSharedObject } from './object.ts';
export { parseAddress } from './channel.ts';
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
