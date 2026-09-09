/** Deterministic ECDSA VRF — SPEC/features/crypto-vrf.md. */

import { sha256 } from '@noble/hashes/sha2.js';
import * as ecdsa from './ecdsa.ts';

export const DOMAIN = new TextEncoder().encode('chaincraft-vrf-v1');

function digest(message: Uint8Array): Uint8Array {
  const input = new Uint8Array(DOMAIN.length + message.length);
  input.set(DOMAIN, 0);
  input.set(message, DOMAIN.length);
  return sha256(input);
}

function output(proof: Uint8Array, pubkey: Uint8Array, message: Uint8Array): Uint8Array {
  const input = new Uint8Array(proof.length + pubkey.length + message.length);
  input.set(proof, 0);
  input.set(pubkey, proof.length);
  input.set(message, proof.length + pubkey.length);
  return sha256(input);
}

export function evaluate(
  message: Uint8Array,
  secretKey: Uint8Array,
): { proof: Uint8Array; output: Uint8Array; publicKey: Uint8Array } {
  const publicKey = ecdsa.publicKey(secretKey);
  const proof = ecdsa.sign(digest(message), secretKey);
  return { proof, output: output(proof, publicKey, message), publicKey };
}

export function verify(
  message: Uint8Array,
  proof: Uint8Array,
  pubkey: Uint8Array,
  expected?: Uint8Array,
): boolean {
  if (!ecdsa.verify(digest(message), proof, pubkey)) return false;
  const computed = output(proof, pubkey, message);
  if (expected !== undefined && expected.some((b, i) => b !== computed[i])) return false;
  if (expected !== undefined && expected.length !== computed.length) return false;
  return true;
}
