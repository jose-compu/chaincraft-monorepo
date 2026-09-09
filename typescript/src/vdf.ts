/** Sloth VDF — SPEC/features/crypto-vdf.md. */

export const P = BigInt(
  '64106875808534963770974826322234655855469213855659218736479077548818158667371',
);

function seedInt(seed: Uint8Array): bigint {
  let n = 0n;
  for (const b of seed) n = (n << 8n) + BigInt(b);
  return n % P;
}

function modPow(base: bigint, exp: bigint, mod: bigint): bigint {
  let result = 1n;
  let b = ((base % mod) + mod) % mod;
  let e = exp;
  while (e > 0n) {
    if (e & 1n) result = (result * b) % mod;
    b = (b * b) % mod;
    e >>= 1n;
  }
  return result;
}

function isResidue(x: bigint): boolean {
  return modPow(x, (P - 1n) / 2n, P) === 1n;
}

function modSqrtOp(x: bigint): bigint {
  const exp = (P + 1n) / 4n;
  if (isResidue(x)) return modPow(x, exp, P);
  return modPow((P - x) % P, exp, P);
}

export function evaluate(seed: Uint8Array, t: number): bigint {
  if (!Number.isSafeInteger(t) || t < 1) {
    throw new Error('t must be a positive integer');
  }
  let x = seedInt(seed);
  for (let i = 0; i < t; i++) x = modSqrtOp(x);
  return x;
}

export function verify(seed: Uint8Array, t: number, proof: bigint): boolean {
  try {
    if (!Number.isSafeInteger(t) || t < 1 || proof < 0n || proof >= P) return false;
    const x = seedInt(seed);
    let y = proof;
    for (let i = 0; i < t; i++) y = modPow(y, 2n, P);
    if (!isResidue(y)) y = (P - y) % P;
    return y === x || y === (P - x) % P;
  } catch {
    return false;
  }
}

export function proofToHex(proof: bigint): string {
  return proof === 0n ? '0' : proof.toString(16);
}

export function hexToProof(text: string): bigint {
  return BigInt('0x' + text);
}
