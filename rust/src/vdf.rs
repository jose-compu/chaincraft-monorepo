//! Sloth VDF — SPEC/features/crypto-vdf.md.

use num_bigint::BigUint;
use num_traits::{One, Zero};

fn modulus() -> BigUint {
    BigUint::parse_bytes(
        b"64106875808534963770974826322234655855469213855659218736479077548818158667371",
        10,
    )
    .unwrap()
}

pub fn evaluate(seed: &[u8], t: u32) -> Result<BigUint, String> {
    if t < 1 {
        return Err("t must be a positive integer".into());
    }
    let p = modulus();
    let mut x = BigUint::from_bytes_be(seed) % &p;
    for _ in 0..t {
        x = mod_sqrt_op(&x, &p);
    }
    Ok(x)
}

pub fn verify(seed: &[u8], t: u32, proof: &BigUint) -> bool {
    if t < 1 {
        return false;
    }
    let p = modulus();
    if proof >= &p {
        return false;
    }
    let x = BigUint::from_bytes_be(seed) % &p;
    let mut y = proof.clone();
    for _ in 0..t {
        y = y.modpow(&BigUint::from(2u32), &p);
    }
    if !is_residue(&y, &p) {
        y = (&p - &y) % &p;
    }
    let neg_x = (&p - &x) % &p;
    y == x || y == neg_x
}

pub fn proof_to_hex(proof: &BigUint) -> String {
    if proof.is_zero() {
        "0".into()
    } else {
        proof.to_str_radix(16)
    }
}

pub fn hex_to_proof(text: &str) -> Result<BigUint, String> {
    BigUint::parse_bytes(text.as_bytes(), 16).ok_or_else(|| "invalid hex".into())
}

fn is_residue(x: &BigUint, p: &BigUint) -> bool {
    let exp = (p - BigUint::one()) >> 1;
    x.modpow(&exp, p) == BigUint::one()
}

fn mod_sqrt_op(x: &BigUint, p: &BigUint) -> BigUint {
    let exp = (p + BigUint::one()) >> 2;
    if is_residue(x, p) {
        x.modpow(&exp, p)
    } else {
        (p - x).modpow(&exp, p)
    }
}
