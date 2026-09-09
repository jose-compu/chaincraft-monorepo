/** secp256k1 ECDSA — SPEC/features/crypto-ecdsa.md. */

import { secp256k1 } from '@noble/curves/secp256k1.js';

const N = BigInt('0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141');
const HALF_N = N / 2n;

export function publicKey(secretKey: Uint8Array): Uint8Array {
  return secp256k1.getPublicKey(secretKey, true);
}

export function sign(message: Uint8Array, secretKey: Uint8Array): Uint8Array {
  return secp256k1.sign(message, secretKey);
}

export function verify(
  message: Uint8Array,
  signature: Uint8Array,
  pubkey: Uint8Array,
): boolean {
  if (signature.length !== 64 || pubkey.length !== 33) return false;
  const s = bytesToBig(signature.subarray(32));
  if (s > HALF_N) return false;
  try {
    return secp256k1.verify(signature, message, pubkey);
  } catch {
    return false;
  }
}

function bytesToBig(bytes: Uint8Array): bigint {
  let n = 0n;
  for (const b of bytes) n = (n << 8n) + BigInt(b);
  return n;
}
