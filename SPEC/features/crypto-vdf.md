# crypto.vdf

**Release:** 1.5.0

Sloth VDF: sequential modular square roots, verified by modular squaring.

Evaluate is intentionally slow. Verify is the same number of cheaper squarings.
The prime, the input encoding and the residue rule are fixed so three languages
produce the same proof for the same `(seed, t)`.

## Parameters

```
p = 64106875808534963770974826322234655855469213855659218736479077548818158667371
```

`p ≡ 3 (mod 4)`, so a square root of a residue `x` is `x^((p+1)/4) mod p`.

`t` is a positive integer. Production delays use large `t`. Vectors use small `t`.

## Evaluate

```
x = int_be(seed) mod p
for i in 1..t:
    if is_residue(x):
        x = x^((p+1)/4)  mod p
    else:
        x = ((-x) mod p)^((p+1)/4)  mod p
proof = x
```

`int_be` is the seed bytes interpreted as an unsigned big-endian integer.
`is_residue(x)` is `x^((p-1)/2) mod p == 1`.

## Verify

```
x = int_be(seed) mod p
y = proof
for i in 1..t:
    y = y^2  mod p
if not is_residue(y):
    y = (-y) mod p
accept if y == x  or  y == ((-x) mod p)
```

## Encoding

`proof` is lowercase hex of the big-endian integer, no `0x`, no leading zeros
unless the value is `0` (then `0`). `t` is a canonical-JSON integer.

`conformance/vectors/vdf.json` pins evaluate and reject cases.
