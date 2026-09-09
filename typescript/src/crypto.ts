/**
 * Signatures — SPEC/wire-v1.md §6.
 *
 * `@noble/curves` backs both algorithms because it runs unmodified in Node and
 * the browser, which the platform crypto APIs do not for BIP-340.
 *
 * Verification never throws: §6 requires malformed input to read as invalid
 * rather than as an exception escaping into the receive path.
 */

import { ed25519 } from '@noble/curves/ed25519.js';
import { schnorr } from '@noble/curves/secp256k1.js';
import { bytesToHex } from './canonical.ts';

export const SCHNORR = 'schnorr';
export const ED25519 = 'ed25519';

export type SignatureAlgorithm = typeof SCHNORR | typeof ED25519;

export const ALGORITHMS: readonly SignatureAlgorithm[] = [SCHNORR, ED25519];

export function isAlgorithm(value: unknown): value is SignatureAlgorithm {
  return value === SCHNORR || value === ED25519;
}

export interface SignResult {
  readonly signature: Uint8Array;
  readonly publicKey: Uint8Array;
}

/** Verify a signature over the 32-byte message. False on any malformed input. */
export function verify(
  alg: string,
  message32: Uint8Array,
  signature: Uint8Array,
  publicKey: Uint8Array,
): boolean {
  if (message32.length !== 32 || signature.length !== 64) return false;
  if (publicKey.length !== 32) return false;
  try {
    if (alg === SCHNORR) {
      return schnorr.verify(signature, message32, publicKey);
    }
    if (alg === ED25519) {
      return ed25519.verify(signature, message32, publicKey);
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * Sign the 32-byte message.
 *
 * `aux` is the BIP-340 auxiliary randomness and is accepted only so conformance
 * vectors can pin deterministic signatures. Production callers omit it.
 */
export function sign(
  alg: SignatureAlgorithm,
  message32: Uint8Array,
  secretKey: Uint8Array,
  aux?: Uint8Array,
): SignResult {
  if (message32.length !== 32) {
    throw new Error('message must be 32 bytes');
  }
  if (alg === SCHNORR) {
    return {
      signature:
        aux === undefined
          ? schnorr.sign(message32, secretKey)
          : schnorr.sign(message32, secretKey, aux),
      publicKey: schnorr.getPublicKey(secretKey),
    };
  }
  return {
    signature: ed25519.sign(message32, secretKey),
    publicKey: ed25519.getPublicKey(secretKey),
  };
}

export function publicKey(
  alg: SignatureAlgorithm,
  secretKey: Uint8Array,
): Uint8Array {
  return alg === SCHNORR
    ? schnorr.getPublicKey(secretKey)
    : ed25519.getPublicKey(secretKey);
}

export function publicKeyHex(
  alg: SignatureAlgorithm,
  secretKey: Uint8Array,
): string {
  return bytesToHex(publicKey(alg, secretKey));
}
