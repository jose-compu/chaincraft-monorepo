#!/usr/bin/env python3
"""Generate the golden conformance vectors from the Python reference core.

Output is deterministic: fixed timestamps, fixed keys, fixed signing nonces. A
diff under conformance/vectors/ therefore means the protocol changed, never that
the generator was run again. See AGENTS.md section 7.

    python3 conformance/generate_vectors.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "python"))
# The Level 1 fixture objects live under tests/ because they are conformance
# scaffolding, not shipped API. See SPEC/semantics-v1.md section 8.
sys.path.insert(0, str(REPO / "python" / "tests"))

from chaincraft_core import control, crypto, framing  # noqa: E402
from chaincraft_core.canonical import canonical_json, payload_digest  # noqa: E402
from chaincraft_core.dedup import DEFAULT_CAPACITY, Deduplicator  # noqa: E402
from chaincraft_core.envelope import Envelope  # noqa: E402
from chaincraft_core.memento import StateMemento  # noqa: E402
from chaincraft_core.object import frontier_digest, merkle_digest, wins_replacement  # noqa: E402
from conformance_objects import build_registry, snapshot  # noqa: E402

VECTORS = REPO / "conformance" / "vectors"

TS = 1757430000000  # fixed reference timestamp for every generated envelope
NOW = 1757430000000
SECKEY = bytes.fromhex(
    "0000000000000000000000000000000000000000000000000000000000000003"
)
AUX = bytes(32)


def header(feature: str, spec: str, description: str) -> Dict[str, Any]:
    return {
        "feature": feature,
        "spec": spec,
        "description": description,
        "generator": "conformance/generate_vectors.py",
        "wire_version": 1,
    }


def sections_of(payload: Dict[str, Any]) -> Dict[str, list]:
    """Case sections, which are the lists of objects. Lists of plain values are
    metadata, such as pipeline.json's registry order."""
    return {
        key: value
        for key, value in payload.items()
        if isinstance(value, list) and all(isinstance(item, dict) for item in value)
    }


def case_count(payload: Dict[str, Any]) -> int:
    total = 0
    for value in sections_of(payload).values():
        total += sum(len(case.get("steps", [1])) for case in value)
    return total


def write(name: str, payload: Dict[str, Any]) -> None:
    path = VECTORS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    summary = ", ".join(f"{len(v)} {k}" for k, v in sections_of(payload).items())
    print(f"  {name:<26} {case_count(payload):>4} cases   {summary}")


# --------------------------------------------------------------------------
# Level 0 section 1 — canonical JSON
# --------------------------------------------------------------------------


def canonical_vectors() -> Dict[str, Any]:
    valid_inputs = [
        ("empty object", "{}"),
        ("empty array", "[]"),
        ("key ordering", '{"b":1,"a":2,"C":3}'),
        ("nested ordering", '{"z":{"b":1,"a":2},"a":[3,1,2]}'),
        ("whitespace stripped", '{ "a" : [ 1 , 2 ] }'),
        ("literals", '{"t":true,"f":false,"n":null}'),
        ("integer zero", "0"),
        ("negative integer", "-42"),
        ("max safe integer", "9007199254740991"),
        ("min safe integer", "-9007199254740991"),
        ("short escapes", '"\\b\\t\\n\\f\\r"'),
        ("quote and backslash", '"a\\"b\\\\c"'),
        ("control characters", '"\\u0000\\u001f"'),
        ("solidus unescaped", '"a/b"'),
        ("non-ascii literal", '"café"'),
        ("cjk literal", '"日本語"'),
        ("emoji literal", '"😀"'),
        ("escaped non-ascii is decoded", '"\\u00e9"'),
        ("unicode key ordering", '{"é":1,"e":2,"z":3}'),
        # A surrogate pair sorts below U+E000 by UTF-16 code unit and above it by
        # code point. Only the second is conformant — wire-v1.md section 1.1.1.
        ("astral plane key ordering", '{"\\uE000":1,"\\ud800\\udc00":2}'),
        ("surrogate pair decoded to one code point", '"\\ud83d\\ude00"'),
        ("array order preserved", "[3,1,2]"),
        ("deeply nested", '{"a":{"b":{"c":{"d":[1,{"e":null}]}}}}'),
    ]

    valid: List[Dict[str, Any]] = []
    for name, raw in valid_inputs:
        value = json.loads(raw)
        valid.append({"name": name, "input_json": raw, "canonical": canonical_json(value)})

    invalid = [
        {"name": "float", "input_json": "1.5", "reason": "floating point not permitted in v1"},
        {"name": "exponent", "input_json": "1e3", "reason": "floating point not permitted in v1"},
        {"name": "negative float", "input_json": "-0.1", "reason": "floating point not permitted in v1"},
        # The token, not the value, is what is rejected. A parser normalizing
        # these to integers is non-conformant — wire-v1.md section 1.3.1.
        {
            "name": "integer-valued float",
            "input_json": "1.0",
            "reason": "fraction in the number token, even though the value is an integer",
        },
        {
            "name": "negative zero float",
            "input_json": "-0.0",
            "reason": "fraction in the number token, even though the value is zero",
        },
        {
            "name": "integer-valued exponent",
            "input_json": "1e2",
            "reason": "exponent in the number token, even though the value is an integer",
        },
        {"name": "integer above safe range", "input_json": "9007199254740992", "reason": "integer outside the safe range"},
        {"name": "integer below safe range", "input_json": "-9007199254740992", "reason": "integer outside the safe range"},
        {"name": "duplicate keys", "input_json": '{"a":1,"a":2}', "reason": "duplicate object key"},
        {"name": "NaN", "input_json": "NaN", "reason": "not valid JSON"},
        {"name": "Infinity", "input_json": "Infinity", "reason": "not valid JSON"},
        {"name": "trailing comma", "input_json": '{"a":1,}', "reason": "not valid JSON"},
        {"name": "single quotes", "input_json": "{'a':1}", "reason": "not valid JSON"},
    ]

    return {
        **header(
            "wire.canonical-json",
            "SPEC/wire-v1.md#1",
            "Parse input_json, re-encode canonically, compare bytes exactly.",
        ),
        "valid": valid,
        "invalid": invalid,
    }


# --------------------------------------------------------------------------
# Level 0 section 2 — payload digest
# --------------------------------------------------------------------------


def digest_vectors() -> Dict[str, Any]:
    payloads = [
        ("empty object", "{}"),
        ("empty array", "[]"),
        ("empty string", '""'),
        ("null", "null"),
        ("integer", "1"),
        ("simple object", '{"n":1}'),
        ("key order irrelevant", '{"b":2,"a":1}'),
        ("key order irrelevant, reversed", '{"a":1,"b":2}'),
        ("nested", '{"tags":[["e","abc"],["p","def"]],"kind":1}'),
        ("non-ascii", '{"msg":"héllo 😀"}'),
    ]
    valid = [
        {
            "name": name,
            "data_json": raw,
            "canonical": canonical_json(json.loads(raw)),
            "digest": payload_digest(json.loads(raw)),
        }
        for name, raw in payloads
    ]
    return {
        **header(
            "wire.payload-digest",
            "SPEC/wire-v1.md#2",
            "digest = lowercase hex sha256 over canonical_json(data).",
        ),
        "valid": valid,
        "invalid": [],
    }


# --------------------------------------------------------------------------
# Level 0 section 3 — envelope
# --------------------------------------------------------------------------


def envelope_vectors() -> Dict[str, Any]:
    built = [
        ("minimal", "app.test", {}),
        ("simple payload", "app.test", {"n": 1}),
        ("nested payload", "app.counter", {"delta": -3, "by": "alice"}),
        ("non-ascii payload", "app.chat", {"msg": "héllo 😀"}),
        ("array payload", "app.batch", [1, 2, 3]),
        ("string payload", "app.ping", "pong"),
    ]
    valid = []
    for name, type_, data in built:
        env = Envelope.build(type_, data, ts=TS)
        valid.append(
            {
                "name": name,
                "type": type_,
                "data_json": canonical_json(data),
                "ts": TS,
                "id": env.id,
                "canonical": env.to_json(),
            }
        )

    good = Envelope.build("app.test", {"n": 1}, ts=TS)
    digest = payload_digest({})
    invalid = [
        {
            "name": "unknown field",
            "envelope_json": '{"data":{},"extra":1,"id":"%s","ts":%d,"type":"app.t","v":1}' % (digest, TS),
            "reason": "unknown envelope field",
        },
        {
            "name": "missing id",
            "envelope_json": '{"data":{},"ts":%d,"type":"app.t","v":1}' % TS,
            "reason": "missing required field",
        },
        {
            "name": "wrong version",
            "envelope_json": '{"data":{},"id":"%s","ts":%d,"type":"app.t","v":2}' % (digest, TS),
            "reason": "unsupported protocol version",
        },
        {
            "name": "digest mismatch",
            "envelope_json": '{"data":{"n":1},"id":"%s","ts":%d,"type":"app.t","v":1}' % ("0" * 64, TS),
            "reason": "id does not match the payload digest",
        },
        {
            "name": "uppercase id",
            "envelope_json": '{"data":{},"id":"%s","ts":%d,"type":"app.t","v":1}' % (digest.upper(), TS),
            "reason": "id must be lowercase hex",
        },
        {
            "name": "invalid type casing",
            "envelope_json": '{"data":{},"id":"%s","ts":%d,"type":"App.Test","v":1}' % (digest, TS),
            "reason": "type must match [a-z0-9._-]{1,64}",
        },
        {
            "name": "float in payload",
            "envelope_json": '{"data":{"x":1.5},"id":"%s","ts":%d,"type":"app.t","v":1}' % (digest, TS),
            "reason": "floating point not permitted in v1",
        },
        {
            "name": "pk without sig",
            "envelope_json": '{"data":{},"id":"%s","pk":"%s","ts":%d,"type":"app.t","v":1}' % (digest, "ab" * 32, TS),
            "reason": "pk and alg require sig",
        },
        {
            "name": "timestamp too far in the future",
            "envelope_json": good.to_json().replace('"ts":%d' % TS, '"ts":%d' % (NOW + 600_000)),
            "reason": "ts more than 300000 ms in the future",
        },
        {
            "name": "not an object",
            "envelope_json": "[]",
            "reason": "envelope must be a JSON object",
        },
    ]

    return {
        **header(
            "wire.envelope",
            "SPEC/wire-v1.md#3",
            "Valid cases build then serialize. Invalid cases must be rejected on "
            "parse; now_ms fixes the clock for timestamp checks.",
        ),
        "now_ms": NOW,
        "valid": valid,
        "invalid": invalid,
    }


# --------------------------------------------------------------------------
# Level 0 section 4 — framing
# --------------------------------------------------------------------------


def framing_vectors() -> Dict[str, Any]:
    bodies = [b"{}", b"hi", b'{"a":1}', "café".encode(), b"x" * 300]
    valid = [
        {
            "name": f"body of {len(body)} bytes",
            "body_hex": body.hex(),
            "frame_hex": framing.encode_frame(body).hex(),
        }
        for body in bodies
    ]

    stream = [
        {
            "name": "single frame split across three chunks",
            "chunks_hex": [
                framing.encode_frame(b"hello world")[:3].hex(),
                framing.encode_frame(b"hello world")[3:7].hex(),
                framing.encode_frame(b"hello world")[7:].hex(),
            ],
            "frames_hex": [b"hello world".hex()],
        },
        {
            "name": "three frames in one chunk",
            "chunks_hex": [
                (
                    framing.encode_frame(b"one")
                    + framing.encode_frame(b"two")
                    + framing.encode_frame(b"three")
                ).hex()
            ],
            "frames_hex": [b"one".hex(), b"two".hex(), b"three".hex()],
        },
        {
            "name": "trailing partial frame is buffered, not emitted",
            "chunks_hex": [(framing.encode_frame(b"one") + b"\x00\x00\x00\x09ab").hex()],
            "frames_hex": [b"one".hex()],
        },
    ]

    invalid = [
        {
            "name": "zero length",
            "input_hex": "00000000",
            "reason": "zero-length frame is invalid",
        },
        {
            "name": "declared length above 16 MiB",
            "input_hex": (framing.MAX_FRAME_BYTES + 1).to_bytes(4, "big").hex(),
            "reason": "declared length exceeds the 16 MiB cap",
        },
    ]

    # UDP carries one envelope per datagram with no length prefix, so the only
    # rules are the size bounds.
    udp_valid = [
        {"name": f"datagram of {len(body)} bytes", "body_hex": body.hex()}
        for body in bodies
    ]
    udp_invalid = [
        {"name": "empty datagram", "input_hex": "", "reason": "zero-length datagram"},
        {
            "name": "datagram above 65507 bytes",
            "input_hex": None,
            "input_length": framing.MAX_UDP_BYTES + 1,
            "reason": "datagram exceeds the 65507 byte cap",
        },
    ]

    return {
        **header(
            "wire.framing-tcp",
            "SPEC/wire-v1.md#4.1",
            "encode: body_hex -> frame_hex. stream: feed chunks_hex in order, "
            "collect frames_hex. invalid: feeding input_hex must raise. udp_*: "
            "section 4.2, no length prefix, size bounds only. Where input_hex is "
            "null, synthesize input_length bytes rather than embedding them.",
        ),
        "max_frame_bytes": framing.MAX_FRAME_BYTES,
        "max_udp_bytes": framing.MAX_UDP_BYTES,
        "valid": valid,
        "stream": stream,
        "invalid": invalid,
        "udp_valid": udp_valid,
        "udp_invalid": udp_invalid,
    }


# --------------------------------------------------------------------------
# Level 0 section 5 — control messages
# --------------------------------------------------------------------------


def control_vectors() -> Dict[str, Any]:
    inner = Envelope.build("app.t", {"n": 1}, ts=TS)
    cases = [
        ("hello minimal", control.hello("py-chaincraft/1.0.0", ts=TS)),
        (
            "hello with listen and caps",
            control.hello(
                "py-chaincraft/1.0.0",
                caps=["udp", "gossip", "digest-sync"],
                listen="10.0.0.2:9735",
                ts=TS,
            ),
        ),
        ("peers request", control.peers_request(ts=TS)),
        ("peers response", control.peers(["10.0.0.2:9735", "10.0.0.3:9735"], ts=TS)),
        ("digest request", control.digest_request("BalanceLedger", ts=TS)),
        ("digest response", control.digest("BalanceLedger", "ab" * 32, ["cd" * 32], ts=TS)),
        ("messages request", control.messages_request("BalanceLedger", "ab" * 32, ts=TS)),
        ("messages response", control.messages("BalanceLedger", [inner], ts=TS)),
    ]
    valid = [
        {"name": name, "type": env.type, "id": env.id, "canonical": env.to_json()}
        for name, env in cases
    ]

    invalid = [
        {
            "name": "hello with unsupported version",
            "envelope_json": Envelope.build(
                control.HELLO, {"v": 99, "impl": "x/1.0", "caps": []}, ts=TS
            ).to_json(),
            "reason": "peer speaks a protocol version we do not support",
        },
        {
            "name": "hello missing impl",
            "envelope_json": Envelope.build(
                control.HELLO, {"v": 1, "caps": []}, ts=TS
            ).to_json(),
            "reason": "ctl.hello requires impl",
        },
    ]

    return {
        **header(
            "wire.control",
            "SPEC/wire-v1.md#5",
            "Constructing each control message must produce these exact bytes. "
            "Invalid cases parse as envelopes but must fail ctl.hello validation.",
        ),
        "now_ms": NOW,
        "valid": valid,
        "invalid": invalid,
    }


# --------------------------------------------------------------------------
# Level 0 section 6 — signatures
# --------------------------------------------------------------------------


def signature_vectors() -> Dict[str, Any]:
    pubkey = crypto.public_key(crypto.SCHNORR, SECKEY)

    env = Envelope.build("app.test", {"n": 1}, ts=TS)
    sig = crypto._schnorr_sign(env.signing_bytes(), SECKEY, AUX)
    signed = Envelope(
        type=env.type,
        data=env.data,
        id=env.id,
        ts=env.ts,
        sig=sig.hex(),
        pk=pubkey.hex(),
        alg="schnorr",
    )

    valid = [
        {
            "name": "BIP-340 reference vector 0",
            "alg": "schnorr",
            "secret_key": "00" * 31 + "03",
            "public_key": "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
            "aux": "00" * 32,
            "message": "00" * 32,
            "signature": (
                "e907831f80848d1069a5371b402410364bdf1c5f8307b0084c55f1ce2dca8215"
                "25f66a4a85ea8b71e482a74f382d2ce5ebeee8fdb2172f477df4900d310536c0"
            ),
        },
        {
            "name": "signed envelope",
            "alg": "schnorr",
            "secret_key": SECKEY.hex(),
            "public_key": pubkey.hex(),
            "aux": AUX.hex(),
            "message": env.id,
            "signature": sig.hex(),
            "canonical": signed.to_json(),
        },
    ]

    invalid = [
        {
            "name": "signature under the wrong key",
            "alg": "schnorr",
            "public_key": "ab" * 32,
            "message": env.id,
            "signature": sig.hex(),
            "reason": "verification must return false, not raise",
        },
        {
            "name": "malformed signature length",
            "alg": "schnorr",
            "public_key": pubkey.hex(),
            "message": env.id,
            "signature": "ab" * 10,
            "reason": "verification must return false, not raise",
        },
        {
            "name": "unknown algorithm",
            "alg": "rsa",
            "public_key": pubkey.hex(),
            "message": env.id,
            "signature": sig.hex(),
            "reason": "unknown algorithms verify as false",
        },
    ]

    return {
        **header(
            "wire.sig-schnorr",
            "SPEC/wire-v1.md#6",
            "The signed message is the hex-decoded id, 32 raw bytes, never "
            "hashed again. Verification returns false on malformed input.",
        ),
        "valid": valid,
        "invalid": invalid,
    }


# --------------------------------------------------------------------------
# Level 0 section 7 — deduplication and relay
# --------------------------------------------------------------------------


def dedup_vectors() -> Dict[str, Any]:
    def run(name: str, capacity: int, envelopes: List[Envelope], note: str) -> Dict[str, Any]:
        dedup = Deduplicator(capacity)
        steps = []
        for env in envelopes:
            # should_process records the digest, so it is called exactly once.
            processed = dedup.should_process(env)
            steps.append(
                {
                    "canonical": env.to_json(),
                    "type": env.type,
                    "id": env.id,
                    "should_process": processed,
                    "should_relay": dedup.should_relay(env),
                    "seen_size": len(dedup.seen),
                }
            )
        return {"name": name, "capacity": capacity, "note": note, "steps": steps}

    def app(n: int, **extra: Any) -> Envelope:
        return Envelope.build("app.counter", {"n": n, **extra}, ts=TS)

    a, b, c = app(1), app(2), app(3)
    hello = control.hello("py-chaincraft/1.0.0", ts=TS)

    sequence = [
        run("first delivery is processed", DEFAULT_CAPACITY, [a], "the base case"),
        run(
            "repeat delivery is suppressed",
            DEFAULT_CAPACITY,
            [a, a],
            "this is what terminates a gossip loop",
        ),
        run(
            "distinct payloads are independent",
            DEFAULT_CAPACITY,
            [a, b],
            "different data, different digest",
        ),
        run(
            "a nonce distinguishes otherwise equal payloads",
            DEFAULT_CAPACITY,
            [app(1, nonce="x"), app(1, nonce="y")],
            "the escape hatch named in section 2 for repeated identical content",
        ),
        run(
            "equal data under different types is one message",
            DEFAULT_CAPACITY,
            [
                Envelope.build("app.a", {"n": 1}, ts=TS),
                Envelope.build("app.b", {"n": 1}, ts=TS),
            ],
            "the digest covers data only, so type does not separate them",
        ),
        run(
            "re-serialization under a new timestamp is still a duplicate",
            DEFAULT_CAPACITY,
            [a, Envelope.build("app.counter", {"n": 1}, ts=TS + 60000)],
            "a relay may rebuild the envelope without breaking downstream dedup",
        ),
        run(
            "control messages are never deduplicated or relayed",
            DEFAULT_CAPACITY,
            [hello, hello],
            "ctl.* is point-to-point, so the set stays empty and relay is false",
        ),
        run(
            "eviction is FIFO by first insertion",
            2,
            [a, b, a, c, a],
            "re-seeing a does not refresh it, so c evicts a and a is new again; "
            "an implementation that refreshed on re-see would report the final "
            "step as a duplicate",
        ),
    ]

    return {
        **header(
            "wire.dedup",
            "SPEC/wire-v1.md#7",
            "Seen-digest set with FIFO eviction. Control messages are never "
            "recorded and never relayed.",
        ),
        "now_ms": NOW,
        "default_capacity": DEFAULT_CAPACITY,
        "sequence": sequence,
    }


# --------------------------------------------------------------------------
# Level 1 section 4 — StateMemento, plus sections 5 and 5.1
# --------------------------------------------------------------------------

D1 = "1" * 64
D2 = "2" * 64
D3 = "3" * 64


def memento_vectors() -> Dict[str, Any]:
    normalize_cases = [
        ("empty", "", []),
        ("canonical digest only", D1, []),
        ("canonical digest joins the frontier", D1, [D2]),
        ("frontier sorted", "", [D3, D1, D2]),
        ("frontier deduplicated", D1, [D1, D1, D2]),
        ("empty entries dropped", "", ["", D1, ""]),
        ("empty canonical digest not appended", "", [D1]),
        ("route independent", D1, [D3, D2, D2]),
    ]
    normalize = []
    for name, canonical, frontier in normalize_cases:
        memento = StateMemento.normalize(canonical, frontier)
        normalize.append(
            {
                "name": name,
                "input": {"canonical_digest": canonical, "frontier_digests": frontier},
                "expected": memento.to_dict(),
            }
        )

    reorg_cases = [
        ("no previous", (D1, []), None),
        ("same head", (D1, []), (D1, [])),
        ("builds on previous head", (D2, [D1]), (D1, [])),
        ("branch without previous head", (D2, [D3]), (D1, [])),
        ("empty current canonical digest", ("", [D2]), (D1, [])),
        ("empty previous canonical digest", (D2, []), ("", [D1])),
    ]
    reorg = []
    for name, current_spec, previous_spec in reorg_cases:
        current = StateMemento.normalize(*current_spec)
        previous = StateMemento.normalize(*previous_spec) if previous_spec else None
        reorg.append(
            {
                "name": name,
                "current": {
                    "canonical_digest": current_spec[0],
                    "frontier_digests": current_spec[1],
                },
                "previous": (
                    {
                        "canonical_digest": previous_spec[0],
                        "frontier_digests": previous_spec[1],
                    }
                    if previous_spec
                    else None
                ),
                "expected": current.indicates_reorg_against(previous),
            }
        )

    merkle_cases = [
        ("empty payload", "{}"),
        ("counter state", '{"previous_digest":"","seq":1,"total":5,"v":1}'),
        ("chained state", '{"previous_digest":"%s","seq":2,"total":2,"v":1}' % D1),
        ("dag payload", '{"parents":["%s","%s"],"v":1}' % (D1, D2)),
        ("key order irrelevant", '{"v":1,"total":5,"seq":1,"previous_digest":""}'),
    ]
    merkle = [
        {
            "name": name,
            "payload_json": raw,
            "canonical": canonical_json(json.loads(raw)),
            "digest": merkle_digest(json.loads(raw)),
        }
        for name, raw in merkle_cases
    ]

    frontier_cases = [
        ("empty", []),
        ("single head", [D1]),
        ("unsorted heads", [D2, D1]),
        ("empty entries dropped", ["", D1]),
        ("three heads", [D3, D1, D2]),
    ]
    frontier = [
        {"name": name, "heads": heads, "digest": frontier_digest(heads)}
        for name, heads in frontier_cases
    ]

    return {
        **header(
            "object.memento",
            "SPEC/semantics-v1.md#4",
            "normalize: apply section 4.1 to input, compare to expected. "
            "reorg: section 4.2. merkle: section 5. frontier: section 5.1.",
        ),
        "normalize": normalize,
        "reorg": reorg,
        "merkle": merkle,
        "frontier": frontier,
    }


# --------------------------------------------------------------------------
# Level 1 sections 3, 6 and 8 — pipeline replay and tie-breaking
# --------------------------------------------------------------------------


def pipeline_vectors() -> Dict[str, Any]:
    sequences = [
        (
            "accepted run",
            [{"delta": 5, "seq": 1}, {"delta": -3, "seq": 2}, {"delta": 10, "seq": 3}],
        ),
        (
            "rejected by counter leaves state untouched",
            [{"delta": 5, "seq": 1}, {"delta": 5, "seq": 99}, {"delta": 5, "seq": 2}],
        ),
        (
            "rejected by mirror is all-or-nothing",
            [
                {"delta": 5, "seq": 1},
                {"delta": 5, "seq": 2, "reject_mirror": True},
                {"delta": 5, "seq": 2},
            ],
        ),
        (
            "out-of-range delta rejected",
            [{"delta": 101, "seq": 1}, {"delta": 100, "seq": 1}],
        ),
        (
            "non-integer fields rejected",
            [{"delta": True, "seq": 1}, {"delta": "1", "seq": 1}, {"delta": 1, "seq": 1}],
        ),
        (
            "redelivery of an applied message is rejected",
            [{"delta": 5, "seq": 1}, {"delta": 5, "seq": 1}],
        ),
    ]

    replay = []
    for name, messages in sequences:
        registry = build_registry()
        steps = []
        for message in messages:
            result = registry.apply(message)
            steps.append(
                {
                    "message_json": canonical_json(message),
                    "accepted": result.accepted,
                    "rejected_by": result.rejected_by,
                    **snapshot(registry),
                }
            )
        replay.append({"name": name, "steps": steps})

    tiebreak_cases = [
        ("higher rank wins", 2, D3, 1, D1),
        ("lower rank loses", 1, D1, 2, D3),
        ("tie broken by lowest digest", 1, D1, 1, D2),
        ("tie, higher digest loses", 1, D2, 1, D1),
        ("identical entry does not replace itself", 1, D1, 1, D1),
        ("negative ranks compare normally", -2, D1, -1, D2),
        ("zero rank against positive", 0, D1, 1, D2),
    ]
    tiebreak = [
        {
            "name": name,
            "candidate": {"rank": c_rank, "digest": c_digest},
            "incumbent": {"rank": i_rank, "digest": i_digest},
            "expected": wins_replacement(c_rank, c_digest, i_rank, i_digest),
        }
        for name, c_rank, c_digest, i_rank, i_digest in tiebreak_cases
    ]

    return {
        **header(
            "object.pipeline",
            "SPEC/semantics-v1.md#3",
            "replay: build the section 8 registry, apply each message in order, "
            "compare state after every step. tiebreak: section 6.1 comparator.",
        ),
        "registry": ["counter", "mirror"],
        "replay": replay,
        "tiebreak": tiebreak,
    }


def main() -> int:
    print("Generating conformance vectors from the Python reference core\n")
    print("Level 0 — wire protocol")
    write("canonical-json.json", canonical_vectors())
    write("digest.json", digest_vectors())
    write("envelope.json", envelope_vectors())
    write("framing.json", framing_vectors())
    write("control.json", control_vectors())
    write("signatures.json", signature_vectors())
    write("dedup.json", dedup_vectors())
    print("\nLevel 1 — object semantics")
    write("memento.json", memento_vectors())
    write("pipeline.json", pipeline_vectors())
    print(f"\nWritten to {VECTORS.relative_to(REPO)}")
    print("A diff here means the wire protocol changed. See AGENTS.md section 7.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
