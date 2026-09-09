//! secp256k1 ECDSA — SPEC/features/crypto-ecdsa.md.

use k256::ecdsa::signature::{Signer, Verifier};
use k256::ecdsa::{Signature, SigningKey, VerifyingKey};

pub fn public_key(secret_key: &[u8]) -> Result<Vec<u8>, String> {
    let sk = SigningKey::from_slice(secret_key).map_err(|e| e.to_string())?;
    Ok(sk
        .verifying_key()
        .to_encoded_point(true)
        .as_bytes()
        .to_vec())
}

pub fn sign(message: &[u8], secret_key: &[u8]) -> Result<Vec<u8>, String> {
    let sk = SigningKey::from_slice(secret_key).map_err(|e| e.to_string())?;
    let sig: Signature = sk.sign(message);
    Ok(sig.to_bytes().to_vec())
}

pub fn verify(message: &[u8], signature: &[u8], pubkey: &[u8]) -> bool {
    if signature.len() != 64 || pubkey.len() != 33 {
        return false;
    }
    let Ok(sig) = Signature::from_slice(signature) else {
        return false;
    };
    if sig.normalize_s().is_some() {
        // high-S: normalize_s returns Some when it had to flip.
        return false;
    }
    let Ok(vk) = VerifyingKey::from_sec1_bytes(pubkey) else {
        return false;
    };
    vk.verify(message, &sig).is_ok()
}
