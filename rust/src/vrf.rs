//! Deterministic ECDSA VRF — SPEC/features/crypto-vrf.md.

use sha2::{Digest, Sha256};

use crate::ecdsa;

pub const DOMAIN: &[u8] = b"chaincraft-vrf-v1";

/// `(proof, output, public_key)` — same order as Python and TypeScript.
pub type Evaluation = (Vec<u8>, Vec<u8>, Vec<u8>);

fn digest(message: &[u8]) -> Vec<u8> {
    let mut h = Sha256::new();
    h.update(DOMAIN);
    h.update(message);
    h.finalize().to_vec()
}

fn output(proof: &[u8], pubkey: &[u8], message: &[u8]) -> Vec<u8> {
    let mut h = Sha256::new();
    h.update(proof);
    h.update(pubkey);
    h.update(message);
    h.finalize().to_vec()
}

pub fn evaluate(message: &[u8], secret_key: &[u8]) -> Result<Evaluation, String> {
    let pubkey = ecdsa::public_key(secret_key)?;
    let proof = ecdsa::sign(&digest(message), secret_key)?;
    let out = output(&proof, &pubkey, message);
    Ok((proof, out, pubkey))
}

pub fn verify(message: &[u8], proof: &[u8], pubkey: &[u8], expected: Option<&[u8]>) -> bool {
    if !ecdsa::verify(&digest(message), proof, pubkey) {
        return false;
    }
    let computed = output(proof, pubkey, message);
    expected
        .map(|want| want == computed.as_slice())
        .unwrap_or(true)
}
