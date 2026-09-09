//! Signatures — SPEC/wire-v1.md §6.
//!
//! Verification never panics or returns `Err`: malformed input is `false`.

use ed25519_dalek::{
    Signature as EdSignature, Signer, SigningKey as EdSigningKey, Verifier,
    VerifyingKey as EdVerifyingKey,
};
use k256::schnorr::{
    signature::hazmat::PrehashSigner, Signature as SchnorrSignature,
    SigningKey as SchnorrSigningKey, VerifyingKey as SchnorrVerifyingKey,
};

use crate::canonical::bytes_to_hex;

pub const SCHNORR: &str = "schnorr";
pub const ED25519: &str = "ed25519";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Algorithm {
    Schnorr,
    Ed25519,
}

impl Algorithm {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Schnorr => SCHNORR,
            Self::Ed25519 => ED25519,
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            SCHNORR => Some(Self::Schnorr),
            ED25519 => Some(Self::Ed25519),
            _ => None,
        }
    }
}

#[derive(Clone, Debug)]
pub struct SignResult {
    pub signature: Vec<u8>,
    pub public_key: Vec<u8>,
}

/// Verify a signature over the 32-byte message. False on any malformed input.
pub fn verify(alg: &str, message32: &[u8], signature: &[u8], public_key: &[u8]) -> bool {
    if message32.len() != 32 || signature.len() != 64 || public_key.len() != 32 {
        return false;
    }
    match alg {
        SCHNORR => verify_schnorr(message32, signature, public_key),
        ED25519 => verify_ed25519(message32, signature, public_key),
        _ => false,
    }
}

fn verify_schnorr(message32: &[u8], signature: &[u8], public_key: &[u8]) -> bool {
    let sig = match SchnorrSignature::try_from(signature) {
        Ok(sig) => sig,
        Err(_) => return false,
    };
    let pk = match SchnorrVerifyingKey::from_bytes(public_key) {
        Ok(pk) => pk,
        Err(_) => return false,
    };
    pk.verify_raw(message32, &sig).is_ok()
}

fn verify_ed25519(message32: &[u8], signature: &[u8], public_key: &[u8]) -> bool {
    let pk_bytes: [u8; 32] = match public_key.try_into() {
        Ok(bytes) => bytes,
        Err(_) => return false,
    };
    let sig_bytes: [u8; 64] = match signature.try_into() {
        Ok(bytes) => bytes,
        Err(_) => return false,
    };
    let pk = match EdVerifyingKey::from_bytes(&pk_bytes) {
        Ok(pk) => pk,
        Err(_) => return false,
    };
    let sig = EdSignature::from_bytes(&sig_bytes);
    pk.verify(message32, &sig).is_ok()
}

/// Sign the 32-byte message. `aux` pins BIP-340 auxiliary randomness for vectors.
pub fn sign(
    alg: Algorithm,
    message32: &[u8],
    secret_key: &[u8],
    aux: Option<&[u8]>,
) -> Result<SignResult, String> {
    if message32.len() != 32 {
        return Err("message must be 32 bytes".into());
    }
    match alg {
        Algorithm::Schnorr => sign_schnorr(message32, secret_key, aux),
        Algorithm::Ed25519 => sign_ed25519(message32, secret_key),
    }
}

fn sign_schnorr(
    message32: &[u8],
    secret_key: &[u8],
    aux: Option<&[u8]>,
) -> Result<SignResult, String> {
    let sk = SchnorrSigningKey::from_bytes(secret_key).map_err(|e| e.to_string())?;
    let signature = match aux {
        Some(aux_bytes) if aux_bytes.len() == 32 => {
            let mut aux_arr = [0u8; 32];
            aux_arr.copy_from_slice(aux_bytes);
            sk.sign_raw(message32, &aux_arr)
                .map_err(|e| e.to_string())?
        }
        Some(_) => return Err("aux must be 32 bytes".into()),
        None => sk.sign_prehash(message32).map_err(|e| e.to_string())?,
    };
    Ok(SignResult {
        signature: signature.to_bytes().to_vec(),
        public_key: sk.verifying_key().to_bytes().to_vec(),
    })
}

fn sign_ed25519(message32: &[u8], secret_key: &[u8]) -> Result<SignResult, String> {
    let sk_bytes: [u8; 32] = secret_key
        .try_into()
        .map_err(|_| "ed25519 secret key must be 32 bytes")?;
    let sk = EdSigningKey::from_bytes(&sk_bytes);
    let signature = sk.sign(message32);
    Ok(SignResult {
        signature: signature.to_bytes().to_vec(),
        public_key: sk.verifying_key().to_bytes().to_vec(),
    })
}

pub fn public_key(alg: Algorithm, secret_key: &[u8]) -> Result<Vec<u8>, String> {
    Ok(sign(alg, &[0u8; 32], secret_key, None)?.public_key)
}

pub fn public_key_hex(alg: Algorithm, secret_key: &[u8]) -> Result<String, String> {
    Ok(bytes_to_hex(&public_key(alg, secret_key)?))
}
