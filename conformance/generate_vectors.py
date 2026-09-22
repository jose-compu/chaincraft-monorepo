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

from chaincraft_core import control, crypto, discovery, ecdsa, framing, vdf, vrf  # noqa: E402
from chaincraft_core.consensus_pbft import PBFT  # noqa: E402
from chaincraft_core.consensus_pos import ProofOfStake, proposer_for  # noqa: E402
from chaincraft_core.consensus_pow import ProofOfWork, block_id, mine  # noqa: E402
from chaincraft_core.fees import charge, estimate, next_base_fee, select  # noqa: E402
from chaincraft_core.ledger_balance import BalanceLedger  # noqa: E402
from chaincraft_core.ledger_utxo import UtxoLedger, transaction_id  # noqa: E402
from chaincraft_core.bittorrent import Swarm, split_payload  # noqa: E402
from chaincraft_core.envelope import ProtocolError  # noqa: E402
from chaincraft_core.nat import (  # noqa: E402
    NatTraversal,
    binding_request,
    binding_success,
    parse_binding_response,
)
from chaincraft_core.cli import NodeSession  # noqa: E402
from chaincraft_core.mempool import Mempool, transaction_id as mempool_tx_id  # noqa: E402
from chaincraft_core.storage import MessageStore  # noqa: E402
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


# --------------------------------------------------------------------------
# Level 2 — crypto primitives
# --------------------------------------------------------------------------


def ecdsa_vectors() -> Dict[str, Any]:
    rfc_key = bytes.fromhex(
        "C9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721"
    )
    valid = []
    for name, key, message in (
        ("empty message, key 3", SECKEY, b""),
        ("sample, RFC 6979 key", rfc_key, b"sample"),
        ("test, RFC 6979 key", rfc_key, b"test"),
        ("binary payload", SECKEY, bytes(range(32))),
    ):
        pk = ecdsa.public_key(key)
        sig = ecdsa.sign(message, key)
        valid.append(
            {
                "name": name,
                "secret_key": key.hex(),
                "public_key": pk.hex(),
                "message_hex": message.hex(),
                "signature": sig.hex(),
            }
        )

    sample_sig = bytes.fromhex(valid[1]["signature"])
    sample_pk = bytes.fromhex(valid[1]["public_key"])
    high_s = sample_sig[:32] + (ecdsa.N - int.from_bytes(sample_sig[32:], "big")).to_bytes(
        32, "big"
    )
    invalid = [
        {
            "name": "high-S signature",
            "public_key": sample_pk.hex(),
            "message_hex": b"sample".hex(),
            "signature": high_s.hex(),
            "reason": "s must be in the lower half of the scalar field",
        },
        {
            "name": "truncated signature",
            "public_key": sample_pk.hex(),
            "message_hex": b"sample".hex(),
            "signature": sample_sig[:31].hex(),
            "reason": "signature must be 64 bytes",
        },
        {
            "name": "wrong public key",
            "public_key": ecdsa.public_key(SECKEY).hex(),
            "message_hex": b"sample".hex(),
            "signature": sample_sig.hex(),
            "reason": "verification must return false, not raise",
        },
        {
            "name": "uncompressed public key rejected",
            "public_key": "04" + "ab" * 32,
            "message_hex": b"sample".hex(),
            "signature": sample_sig.hex(),
            "reason": "only 33-byte compressed keys are valid",
        },
    ]
    return {
        **header(
            "crypto.ecdsa",
            "SPEC/features/crypto-ecdsa.md",
            "secp256k1 ECDSA, SHA-256, compact r||s, low-S, compressed pubkey.",
        ),
        "valid": valid,
        "invalid": invalid,
    }


def vdf_vectors() -> Dict[str, Any]:
    valid = []
    for name, seed, t in (
        ("ascii seed, t=8", b"TestVDF", 8),
        ("empty seed, t=4", b"", 4),
        ("binary seed, t=16", bytes.fromhex("00ff"), 16),
    ):
        proof = vdf.evaluate(seed, t)
        valid.append(
            {
                "name": name,
                "seed_hex": seed.hex(),
                "t": t,
                "proof": vdf.proof_to_hex(proof),
            }
        )
    invalid = [
        {
            "name": "proof plus one",
            "seed_hex": b"TestVDF".hex(),
            "t": 8,
            "proof": vdf.proof_to_hex(vdf.evaluate(b"TestVDF", 8) + 1),
            "reason": "altered proof must not verify",
        },
        {
            "name": "wrong seed",
            "seed_hex": b"Other".hex(),
            "t": 8,
            "proof": vdf.proof_to_hex(vdf.evaluate(b"TestVDF", 8)),
            "reason": "proof is bound to the seed",
        },
        {
            "name": "zero iterations",
            "seed_hex": b"TestVDF".hex(),
            "t": 0,
            "proof": "1",
            "reason": "t must be positive",
        },
    ]
    return {
        **header(
            "crypto.vdf",
            "SPEC/features/crypto-vdf.md",
            "Sloth VDF: sequential square roots, verify by squaring.",
        ),
        "modulus": vdf.proof_to_hex(vdf.P),
        "valid": valid,
        "invalid": invalid,
    }


def vrf_vectors() -> Dict[str, Any]:
    valid = []
    for name, key, message in (
        ("hello", SECKEY, b"Hello VRF"),
        ("empty", SECKEY, b""),
        ("sample", SECKEY, b"sample"),
    ):
        proof, output, pk = vrf.evaluate(message, key)
        valid.append(
            {
                "name": name,
                "secret_key": key.hex(),
                "public_key": pk.hex(),
                "message_hex": message.hex(),
                "proof": proof.hex(),
                "output": output.hex(),
            }
        )
    hello = valid[0]
    invalid = [
        {
            "name": "wrong message",
            "public_key": hello["public_key"],
            "message_hex": b"Attack VRF".hex(),
            "proof": hello["proof"],
            "output": hello["output"],
            "reason": "proof is bound to the message",
        },
        {
            "name": "truncated proof",
            "public_key": hello["public_key"],
            "message_hex": hello["message_hex"],
            "proof": hello["proof"][:20],
            "output": hello["output"],
            "reason": "malformed proof is invalid",
        },
    ]
    return {
        **header(
            "crypto.vrf",
            "SPEC/features/crypto-vrf.md",
            "Deterministic ECDSA VRF. Same (sk, message) yields the same proof.",
        ),
        "domain": "chaincraft-vrf-v1",
        "valid": valid,
        "invalid": invalid,
    }


# --------------------------------------------------------------------------
# Level 2 — discovery
# --------------------------------------------------------------------------


def _book_state(book: discovery.AddressBook) -> Dict[str, Any]:
    return {
        "size": len(book),
        "book": book.addresses(),
        "advertised": book.advertise(),
    }


def discovery_peer_vectors() -> Dict[str, Any]:
    valid = [
        "10.0.0.2:9735",
        "10.0.0.10:9735",
        "127.0.0.1:1",
        "0.0.0.0:65535",
        "localhost:9735",
        "node-a.local:8080",
    ]
    invalid = [
        ("empty", ""),
        ("missing port", "10.0.0.2"),
        ("port zero", "10.0.0.2:0"),
        ("port leading zero", "10.0.0.2:09735"),
        ("port too large", "10.0.0.2:65536"),
        ("ipv4 octet 256", "256.0.0.1:9735"),
        ("ipv4 leading zero", "10.0.0.01:9735"),
        ("ipv6", "[::1]:9735"),
        ("underscore host", "node_a:9735"),
        ("trailing hyphen", "node-.local:9735"),
        ("space", "10.0.0.2: 9735"),
    ]

    listen = "10.0.0.1:9735"
    now = NOW

    def run(name: str, note: str, ops) -> Dict[str, Any]:
        book = discovery.AddressBook(listen=listen, capacity=3, timeout_ms=120_000)
        steps = []
        for op in ops:
            kind = op["op"]
            clock = op.get("now_ms", now)
            if kind == "insert":
                added = book.insert(op["address"], clock)
                step = {"op": "insert", "address": op["address"], "now_ms": clock, "added": added}
            elif kind == "ingest":
                count = book.ingest(op["addresses"], clock, op["solicited"])
                step = {
                    "op": "ingest",
                    "addresses": list(op["addresses"]),
                    "solicited": op["solicited"],
                    "now_ms": clock,
                    "added": count,
                }
            elif kind == "sweep":
                expired = book.sweep(clock)
                step = {"op": "sweep", "now_ms": clock, "expired": expired}
            elif kind == "advertise":
                step = {"op": "advertise", "advertised": book.advertise()}
            else:
                raise ValueError(kind)
            step.update(_book_state(book))
            steps.append(step)
        return {"name": name, "note": note, "capacity": 3, "listen": listen, "steps": steps}

    a, b, c, d = "10.0.0.2:9735", "10.0.0.3:9735", "10.0.0.4:9735", "10.0.0.5:9735"
    later = now + 60_000
    stale = now + 120_001

    sequence = [
        run(
            "insert and reject self",
            "listen is never stored; a fresh address is",
            [
                {"op": "insert", "address": listen},
                {"op": "insert", "address": a},
            ],
        ),
        run(
            "re-see updates last_seen without moving eviction rank",
            "same no-refresh rule as wire.dedup",
            [
                {"op": "insert", "address": a},
                {"op": "insert", "address": b},
                {"op": "insert", "address": a, "now_ms": later},
                {"op": "insert", "address": c},
                {"op": "insert", "address": d},
            ],
        ),
        run(
            "ingest fills remaining slots and never evicts",
            "a ctl.peers flood must not rotate the book",
            [
                {"op": "insert", "address": a},
                {"op": "insert", "address": b},
                {
                    "op": "ingest",
                    "addresses": [c, d, "10.0.0.6:9735"],
                    "solicited": True,
                },
            ],
        ),
        run(
            "unsolicited ingest is ignored",
            "wire-v1 section 5.2",
            [
                {"op": "ingest", "addresses": [a, b], "solicited": False},
            ],
        ),
        run(
            "invalid and self addresses are skipped",
            "ingest never raises",
            [
                {
                    "op": "ingest",
                    "addresses": [listen, "256.0.0.1:9735", a, "bad"],
                    "solicited": True,
                },
            ],
        ),
        run(
            "advertise is sorted by code point",
            "10.0.0.10 precedes 10.0.0.2",
            [
                {"op": "insert", "address": "10.0.0.2:9735"},
                {"op": "insert", "address": "10.0.0.10:9735"},
                {"op": "advertise"},
            ],
        ),
        run(
            "sweep expires by last_seen",
            "timeout is exclusive: equal is kept",
            [
                {"op": "insert", "address": a, "now_ms": now},
                {"op": "insert", "address": b, "now_ms": later},
                {"op": "sweep", "now_ms": stale},
            ],
        ),
    ]

    return {
        **header(
            "discovery.peer",
            "SPEC/features/discovery-peer.md",
            "Address book: IPv4/hostname:port, FIFO insert eviction, "
            "no-evict ingest, code-point advertise, injected clock.",
        ),
        "now_ms": NOW,
        "default_capacity": discovery.DEFAULT_CAPACITY,
        "default_timeout_ms": discovery.DEFAULT_TIMEOUT_MS,
        "valid": [{"name": addr, "address": addr} for addr in valid],
        "invalid": [{"name": name, "address": addr} for name, addr in invalid],
        "sequence": sequence,
    }


def discovery_local_vectors() -> Dict[str, Any]:
    listen = "10.0.0.1:9735"
    neighbor = "10.0.0.2:9735"
    a, b = "10.0.0.3:9735", "10.0.0.4:9735"
    now = NOW

    def run(name: str, note: str, enabled: bool, ops) -> Dict[str, Any]:
        book = discovery.AddressBook(listen=listen, capacity=50)
        local = discovery.LocalDiscovery(book, enabled=enabled)
        steps = []
        for op in ops:
            kind = op["op"]
            clock = op.get("now_ms", now)
            if kind == "insert":
                added = book.insert(op["address"], clock)
                step = {"op": "insert", "address": op["address"], "now_ms": clock, "added": added}
            elif kind == "request":
                ok = local.request(op["peer"])
                step = {
                    "op": "request",
                    "peer": op["peer"],
                    "ok": ok,
                    "solicited": book.is_solicited(op["peer"]),
                }
            elif kind == "reply":
                peers = local.reply()
                step = {"op": "reply", "peers": peers}
            elif kind == "accept":
                count = local.accept(op["from"], op["addresses"], clock)
                step = {
                    "op": "accept",
                    "from": op["from"],
                    "addresses": list(op["addresses"]),
                    "now_ms": clock,
                    "added": count,
                    "solicited": book.is_solicited(op["from"]),
                }
            else:
                raise ValueError(kind)
            step.update(_book_state(book))
            steps.append(step)
        return {
            "name": name,
            "note": note,
            "enabled": enabled,
            "listen": listen,
            "steps": steps,
        }

    sequence = [
        run(
            "enabled request, reply and accept",
            "solicited neighbor's list is ingested",
            True,
            [
                {"op": "insert", "address": neighbor},
                {"op": "insert", "address": a},
                {"op": "request", "peer": neighbor},
                {"op": "reply"},
                {"op": "accept", "from": neighbor, "addresses": [a, b]},
            ],
        ),
        run(
            "disabled neither replies nor accepts",
            "the book only changes through insert",
            False,
            [
                {"op": "insert", "address": neighbor},
                {"op": "request", "peer": neighbor},
                {"op": "reply"},
                {"op": "accept", "from": neighbor, "addresses": [a, b]},
            ],
        ),
        run(
            "unsolicited accept is ignored even when enabled",
            "request must precede accept",
            True,
            [
                {"op": "accept", "from": neighbor, "addresses": [a]},
            ],
        ),
    ]

    return {
        **header(
            "discovery.local",
            "SPEC/features/discovery-local.md",
            "Local peer-list policy over ctl.peers. Disabled nodes do not "
            "share or learn addresses.",
        ),
        "now_ms": NOW,
        "sequence": sequence,
    }


def _replay_object(name: str, factory, messages: List[Any]) -> Dict[str, Any]:
    obj = factory()
    steps = []
    for message in messages:
        accepted = obj.is_valid(message)
        if accepted:
            obj.add_message(message)
        steps.append(
            {
                "message_json": canonical_json(message),
                "accepted": accepted,
                **obj.state(),
            }
        )
    return {"name": name, "steps": steps}


def consensus_pow_vectors() -> Dict[str, Any]:
    difficulty = 2
    genesis = mine("", 1, "alice", "one", difficulty)
    child = mine(genesis["id"], 2, "alice", "two", difficulty)
    fork = mine("", 1, "bob", "alt", difficulty)
    low, high = (genesis, fork) if genesis["id"] < fork["id"] else (fork, genesis)
    wire = {k: genesis[k] for k in ("consensus", "height", "miner", "nonce", "parent", "payload")}
    weak_nonce = 0
    while True:
        digest = block_id(1, "alice", weak_nonce, "", "one")
        if not digest.startswith("00"):
            break
        weak_nonce += 1
    replay = [
        _replay_object("empty then two-block chain", lambda: ProofOfWork(difficulty), [genesis, child]),
        _replay_object(
            "same-height fork prefers lowest id",
            lambda: ProofOfWork(difficulty),
            [high, low],
        ),
        _replay_object(
            "duplicate block rejected",
            lambda: ProofOfWork(difficulty),
            [genesis, genesis],
        ),
        _replay_object(
            "wrong parent height rejected",
            lambda: ProofOfWork(difficulty),
            [genesis, {**child, "parent": "", "height": 2}],
        ),
        _replay_object(
            "insufficient work rejected",
            lambda: ProofOfWork(difficulty),
            [{**wire, "nonce": weak_nonce}],
        ),
    ]
    return {
        **header(
            "consensus.pow",
            "SPEC/features/consensus-pow.md",
            "PoW object: leading-zero work, longest tip, lowest-id tie-break.",
        ),
        "difficulty": difficulty,
        "replay": replay,
    }


def consensus_pos_vectors() -> Dict[str, Any]:
    pos = ProofOfStake()
    schedule = [
        {"slot": slot, "proposer": proposer_for(slot, pos.seed, pos.validators)}
        for slot in range(1, 5)
    ]
    good = [
        {
            "consensus": "pos",
            "payload": f"p{item['slot']}",
            "proposer": item["proposer"],
            "slot": item["slot"],
        }
        for item in schedule[:2]
    ]
    wrong = {**good[0], "proposer": "carol" if good[0]["proposer"] != "carol" else "bob"}
    replay = [
        _replay_object("two scheduled slots", ProofOfStake, good),
        _replay_object("wrong proposer rejected", ProofOfStake, [wrong, good[0]]),
        _replay_object("skipping a slot rejected", ProofOfStake, [{**good[1]}]),
    ]
    return {
        **header(
            "consensus.pos",
            "SPEC/features/consensus-pos.md",
            "PoS object: weighted lottery over a fixed validator set.",
        ),
        "seed": pos.seed,
        "validators": pos.validators,
        "schedule": schedule,
        "replay": replay,
    }


def consensus_pbft_vectors() -> Dict[str, Any]:
    value = "hello"
    digest = merkle_digest(value)
    view, seq = 0, 1

    def vote(phase: str, replica: str) -> Dict[str, Any]:
        msg: Dict[str, Any] = {
            "consensus": "pbft",
            "digest": digest,
            "phase": phase,
            "replica": replica,
            "sequence": seq,
            "view": view,
        }
        if phase == "pre-prepare":
            msg["value"] = value
        return msg

    happy = [
        vote("pre-prepare", "r0"),
        vote("prepare", "r0"),
        vote("prepare", "r1"),
        vote("prepare", "r2"),
        vote("commit", "r0"),
        vote("commit", "r1"),
        vote("commit", "r2"),
    ]
    bad_primary = {**vote("pre-prepare", "r1"), "value": value}
    future = {**vote("prepare", "r1"), "sequence": 9}
    replay = [
        _replay_object("quorum execute", PBFT, happy),
        _replay_object("non-primary pre-prepare rejected", PBFT, [bad_primary]),
        _replay_object("out-of-sequence prepare is valid but ignored", PBFT, [future]),
    ]
    return {
        **header(
            "consensus.pbft",
            "SPEC/features/consensus-pbft.md",
            "PBFT object: pre-prepare / prepare / commit, quorum 2f+1.",
        ),
        "replicas": list(PBFT().replicas),
        "quorum": PBFT().quorum,
        "value_digest": digest,
        "replay": replay,
    }


def ledger_balance_vectors() -> Dict[str, Any]:
    def transfer(
        sender: str, recipient: str, amount: int, fee: int, nonce: int
    ) -> Dict[str, Any]:
        return {
            "ledger": "balance",
            "sender": sender,
            "recipient": recipient,
            "amount": amount,
            "fee": fee,
            "nonce": nonce,
        }

    first = transfer("alice", "bob", 10, 2, 0)
    second = transfer("alice", "bob", 1, 0, 1)
    replay = [
        _replay_object("transfer and fee burn", BalanceLedger, [first]),
        _replay_object("second nonce accepted", BalanceLedger, [first, second]),
        _replay_object(
            "insufficient balance rejected",
            BalanceLedger,
            [transfer("bob", "alice", 5, 1, 0)],
        ),
        _replay_object(
            "wrong nonce rejected",
            BalanceLedger,
            [transfer("alice", "bob", 1, 0, 5)],
        ),
        _replay_object(
            "self-transfer burns fee",
            BalanceLedger,
            [transfer("alice", "alice", 10, 3, 0)],
        ),
        _replay_object(
            "zero amount rejected",
            BalanceLedger,
            [transfer("alice", "bob", 0, 0, 0)],
        ),
    ]
    return {
        **header(
            "ledger.balance",
            "SPEC/features/ledger-balance.md",
            "Account ledger: nonce, no overdraft, fee burned.",
        ),
        "allocations": {"alice": 100},
        "replay": replay,
    }


def ledger_utxo_vectors() -> Dict[str, Any]:
    spend = {
        "ledger": "utxo",
        "fee": 2,
        "inputs": ["genesis:alice"],
        "outputs": [
            {"owner": "bob", "value": 70},
            {"owner": "alice", "value": 28},
        ],
    }
    first_id = transaction_id(2, spend["inputs"], spend["outputs"])
    chained = {
        "ledger": "utxo",
        "fee": 0,
        "inputs": [f"{first_id}:0"],
        "outputs": [{"owner": "carol", "value": 70}],
    }
    burn = {
        "ledger": "utxo",
        "fee": 100,
        "inputs": ["genesis:alice"],
        "outputs": [],
    }
    replay = [
        _replay_object("spend with change and fee", UtxoLedger, [spend]),
        _replay_object("spend a created output", UtxoLedger, [spend, chained]),
        _replay_object("full burn", UtxoLedger, [burn]),
        _replay_object(
            "double spend rejected",
            UtxoLedger,
            [spend, {**spend, "outputs": [{"owner": "carol", "value": 98}]}],
        ),
        _replay_object(
            "duplicate input rejected",
            UtxoLedger,
            [
                {
                    "ledger": "utxo",
                    "fee": 0,
                    "inputs": ["genesis:alice", "genesis:alice"],
                    "outputs": [{"owner": "bob", "value": 100}],
                }
            ],
        ),
        _replay_object(
            "value mismatch rejected",
            UtxoLedger,
            [
                {
                    "ledger": "utxo",
                    "fee": 0,
                    "inputs": ["genesis:alice"],
                    "outputs": [{"owner": "bob", "value": 200}],
                }
            ],
        ),
        _replay_object(
            "missing input rejected",
            UtxoLedger,
            [
                {
                    "ledger": "utxo",
                    "fee": 0,
                    "inputs": ["does-not-exist"],
                    "outputs": [{"owner": "bob", "value": 1}],
                }
            ],
        ),
    ]
    return {
        **header(
            "ledger.utxo",
            "SPEC/features/ledger-utxo.md",
            "UTXO ledger: structural fee, insertion-order store, fee burned.",
        ),
        "allocations": {"alice": 100},
        "replay": replay,
    }


def _tx(sender: str, nonce: int, fee: int, payload: str = "p") -> Dict[str, Any]:
    return {"fee": fee, "nonce": nonce, "payload": payload, "sender": sender}


def mempool_basic_vectors() -> Dict[str, Any]:
    def run(name: str, note: str, kwargs: Dict[str, Any], ops) -> Dict[str, Any]:
        pool = Mempool(**kwargs)
        steps = []
        for op in ops:
            kind = op["op"]
            if kind == "insert":
                result = pool.insert(op["tx"], op["now_ms"])
                step = {"op": "insert", "tx": op["tx"], "now_ms": op["now_ms"], **result}
            elif kind == "remove":
                step = {"op": "remove", "id": op["id"], "removed": pool.remove(op["id"])}
            elif kind == "sweep":
                step = {"op": "sweep", "now_ms": op["now_ms"], "expired": pool.sweep(op["now_ms"])}
            else:
                raise ValueError(kind)
            step["ids"] = pool.ids()
            step["size"] = len(pool)
            steps.append(step)
        return {"name": name, "note": note, **kwargs, "steps": steps}

    now = NOW
    low = _tx("a", 0, 1)
    mid = _tx("b", 0, 5)
    high = _tx("c", 0, 9)
    first = _tx("alice", 0, 3)
    better = _tx("alice", 0, 5, "q")
    too_low = _tx("alice", 0, 3, "r")
    alice1 = _tx("alice", 1, 3)
    carol = _tx("carol", 0, 3)
    sequence = [
        run(
            "min fee and duplicate rejected",
            "floor then content-addressed id",
            {"capacity": 8, "min_fee": 5, "ttl_ms": 60_000, "max_per_sender": 0, "rbf_min_increase": 1},
            [
                {"op": "insert", "tx": _tx("alice", 0, 4), "now_ms": now},
                {"op": "insert", "tx": _tx("alice", 0, 5), "now_ms": now},
                {"op": "insert", "tx": _tx("alice", 0, 5), "now_ms": now},
            ],
        ),
        run(
            "replace by fee",
            "same sender and nonce, higher fee replaces",
            {"capacity": 8, "min_fee": 0, "ttl_ms": 60_000, "max_per_sender": 0, "rbf_min_increase": 1},
            [
                {"op": "insert", "tx": first, "now_ms": now},
                {"op": "insert", "tx": better, "now_ms": now},
                {"op": "insert", "tx": too_low, "now_ms": now},
            ],
        ),
        run(
            "per-sender cap",
            "a replacement is not a second slot",
            {"capacity": 8, "min_fee": 0, "ttl_ms": 60_000, "max_per_sender": 1, "rbf_min_increase": 1},
            [
                {"op": "insert", "tx": first, "now_ms": now},
                {"op": "insert", "tx": alice1, "now_ms": now},
                {"op": "insert", "tx": carol, "now_ms": now},
                {"op": "insert", "tx": better, "now_ms": now},
            ],
        ),
        run(
            "full pool evicts lowest fee",
            "ties keep the earlier insertion",
            {"capacity": 2, "min_fee": 0, "ttl_ms": 60_000, "max_per_sender": 0, "rbf_min_increase": 1},
            [
                {"op": "insert", "tx": low, "now_ms": now},
                {"op": "insert", "tx": mid, "now_ms": now},
                {"op": "insert", "tx": high, "now_ms": now},
                {"op": "insert", "tx": _tx("d", 0, 2), "now_ms": now},
            ],
        ),
        run(
            "ttl sweep and remove",
            "expiry uses the injected clock",
            {"capacity": 8, "min_fee": 0, "ttl_ms": 10, "max_per_sender": 0, "rbf_min_increase": 1},
            [
                {"op": "insert", "tx": low, "now_ms": now},
                {"op": "insert", "tx": mid, "now_ms": now + 15},
                {"op": "remove", "id": mempool_tx_id(5, 0, "p", "b")},
                {"op": "sweep", "now_ms": now + 15},
            ],
        ),
    ]
    return {
        **header(
            "mempool.basic",
            "SPEC/features/mempool-basic.md",
            "Mempool: min fee, RBF, sender cap, lowest-fee eviction, TTL.",
        ),
        "now_ms": now,
        "sequence": sequence,
    }


def fees_policy_vectors() -> Dict[str, Any]:
    ranking = [
        {"id": "b", "fee": 1},
        {"id": "a", "fee": 9},
        {"id": "c", "fee": 9},
        {"id": "d", "fee": 5},
        {"id": "", "fee": 99},
        {"id": "a", "fee": 1},
    ]
    select_cases = [
        {
            "name": "highest fee then lowest id",
            "candidates": ranking,
            "limit": 3,
            "ids": select(ranking, 3),
        },
        {
            "name": "limit one",
            "candidates": ranking,
            "limit": 1,
            "ids": select(ranking, 1),
        },
    ]
    charge_cases = [
        {"name": "tip only", "fee": 7, "base": 0, **charge(7, 0)},
        {"name": "base burned", "fee": 8, "base": 5, **charge(8, 5)},
        {"name": "fee below base", "fee": 3, "base": 5, **charge(3, 5)},
    ]
    estimate_cases = [
        {"name": "empty", "fees": [], "estimate": estimate([])},
        {"name": "odd", "fees": [10, 6, 2], "estimate": estimate([10, 6, 2])},
        {"name": "even floor average", "fees": [10, 7, 5, 2], "estimate": estimate([10, 7, 5, 2])},
    ]
    base_cases = [
        {
            "name": "at target",
            "base": 100,
            "parent_count": 5,
            "target": 5,
            "next": next_base_fee(100, 5, 5),
        },
        {
            "name": "above target",
            "base": 100,
            "parent_count": 10,
            "target": 5,
            "next": next_base_fee(100, 10, 5),
        },
        {
            "name": "below target",
            "base": 100,
            "parent_count": 0,
            "target": 5,
            "next": next_base_fee(100, 0, 5),
        },
        {
            "name": "floor is one",
            "base": 1,
            "parent_count": 0,
            "target": 5,
            "next": next_base_fee(1, 0, 5),
        },
    ]
    return {
        **header(
            "fees.policy",
            "SPEC/features/fees-policy.md",
            "Fee policy: rank, burn split, median estimate, integer base-fee step.",
        ),
        "select": select_cases,
        "charge": charge_cases,
        "estimate": estimate_cases,
        "base_fee": base_cases,
    }


def storage_persistent_vectors() -> Dict[str, Any]:
    a = payload_digest({"n": 1})
    b = payload_digest({"n": 2})
    c = payload_digest({"n": 3})

    def run(name: str, note: str, capacity: int, ops) -> Dict[str, Any]:
        store = MessageStore(capacity)
        steps = []
        for op in ops:
            kind = op["op"]
            if kind == "put":
                added = store.put(op["id"], op["body"])
                step = {"op": "put", "id": op["id"], "body": op["body"], "added": added}
            elif kind == "get":
                step = {"op": "get", "id": op["id"], **store.get(op["id"])}
            elif kind == "remove":
                step = {"op": "remove", "id": op["id"], "removed": store.remove(op["id"])}
            elif kind == "load":
                step = {"op": "load", "snapshot": op["snapshot"], "ok": store.load(op["snapshot"])}
            else:
                raise ValueError(kind)
            step["ids"] = store.ids()
            step["size"] = len(store)
            step["dump"] = store.dump()
            steps.append(step)
        return {"name": name, "note": note, "capacity": capacity, "steps": steps}

    snapshot = {
        "entries": [{"body": "one", "id": a}, {"body": "two", "id": b}],
        "v": 1,
    }
    bad = {"entries": [{"body": "one", "id": a}, {"body": "dup", "id": a}], "v": 1}
    sequence = [
        run(
            "put get overwrite and remove",
            "replace does not move eviction rank",
            8,
            [
                {"op": "put", "id": a, "body": "one"},
                {"op": "put", "id": b, "body": "two"},
                {"op": "put", "id": a, "body": "ONE"},
                {"op": "get", "id": a},
                {"op": "get", "id": "0" * 64},
                {"op": "remove", "id": b},
            ],
        ),
        run(
            "fifo eviction",
            "oldest insertion is dropped first",
            2,
            [
                {"op": "put", "id": a, "body": "one"},
                {"op": "put", "id": b, "body": "two"},
                {"op": "put", "id": c, "body": "three"},
            ],
        ),
        run(
            "load replaces; bad snapshot is rejected",
            "capacity and uniqueness are enforced",
            2,
            [
                {"op": "put", "id": c, "body": "keep"},
                {"op": "load", "snapshot": snapshot},
                {"op": "load", "snapshot": bad},
            ],
        ),
        run(
            "invalid id rejected",
            "id must be 64 lowercase hex",
            8,
            [{"op": "put", "id": "not-hex", "body": "x"}],
        ),
    ]
    return {
        **header(
            "storage.persistent",
            "SPEC/features/storage-persistent.md",
            "Message store: content-addressed put, FIFO eviction, dump/load.",
        ),
        "sequence": sequence,
    }


def cli_node_vectors() -> Dict[str, Any]:
    impl = "py-chaincraft/1.0.0"
    listen = "127.0.0.1:21000"
    peer = "10.0.0.2:9735"

    def run(name: str, note: str, ops) -> Dict[str, Any]:
        session = NodeSession(impl, listen)
        steps = []
        for op in ops:
            kind = op["op"]
            if kind == "start":
                events = session.start()
                step = {"op": "start", "events": events}
            elif kind == "line":
                events = session.handle(op["line"])
                step = {"op": "line", "line": op["line"], "events": events}
            else:
                raise ValueError(kind)
            step.update(session.state())
            steps.append(step)
        return {
            "name": name,
            "note": note,
            "impl": impl,
            "listen": listen,
            "steps": steps,
        }

    send = canonical_json({"cmd": "send", "data": {"n": 1}, "type": "app.interop"})
    sequence = [
        run(
            "start connect send and ids",
            "payload digest is the sent id",
            [
                {"op": "start"},
                {"op": "line", "line": canonical_json({"addr": peer, "cmd": "connect"})},
                {"op": "line", "line": canonical_json({"addr": peer, "cmd": "connect"})},
                {"op": "line", "line": send},
                {"op": "line", "line": canonical_json({"cmd": "ids"})},
            ],
        ),
        run(
            "rejects and quit",
            "closed session accepts no further commands",
            [
                {"op": "start"},
                {"op": "line", "line": "   "},
                {"op": "line", "line": "{not json"},
                {"op": "line", "line": canonical_json({"cmd": "connect", "addr": "bad"})},
                {"op": "line", "line": canonical_json({"cmd": "send", "type": "Nope", "data": {}})},
                {"op": "line", "line": canonical_json({"cmd": "nope"})},
                {"op": "line", "line": canonical_json({"cmd": "quit"})},
                {"op": "line", "line": canonical_json({"cmd": "ids"})},
            ],
        ),
    ]
    return {
        **header(
            "cli.node",
            "SPEC/features/cli-node.md",
            "JSON-lines node commands and events, no sockets.",
        ),
        "impl": impl,
        "listen": listen,
        "sequence": sequence,
    }


def bittorrent_swarm_vectors() -> Dict[str, Any]:
    seed = split_payload("demo", "ABCDEFGHIJKL", 4)
    digest = seed["info_hash"]
    corrupt = "00" * 4
    replay = []

    def run(name: str, note: str, messages: List[Any]) -> Dict[str, Any]:
        obj = Swarm()
        steps = []
        for message in messages:
            accepted = obj.is_valid(message)
            if accepted:
                obj.add_message(message)
            snap = obj.state()
            steps.append(
                {
                    "accepted": accepted,
                    "assembled": obj.assembled(digest),
                    "message": message,
                    "state": snap,
                }
            )
        return {"name": name, "note": note, "info_hash": digest, "steps": steps}

    metainfo = {"bt": "metainfo", "name": "demo", "pieces": seed["pieces"]}
    pieces = [
        {
            "bt": "piece",
            "data": payload,
            "index": index,
            "info_hash": digest,
            "peer": "alice",
        }
        for index, payload in enumerate(seed["payloads"])
    ]
    replay.append(
        run(
            "seed three pieces",
            "alice completes; assembled bytes match",
            [metainfo, *pieces],
        )
    )
    replay.append(
        run(
            "have without data",
            "bob is advertised only",
            [
                metainfo,
                {"bt": "have", "index": 0, "info_hash": digest, "peer": "bob"},
            ],
        )
    )
    replay.append(
        run(
            "corrupt piece rejected",
            "hash mismatch does not mutate",
            [
                metainfo,
                {
                    "bt": "piece",
                    "data": corrupt,
                    "index": 0,
                    "info_hash": digest,
                    "peer": "alice",
                },
            ],
        )
    )
    replay.append(
        run(
            "idempotent metainfo and request",
            "request is valid and leaves state unchanged",
            [
                metainfo,
                metainfo,
                {"bt": "request", "index": 0, "info_hash": digest, "peer": "bob"},
            ],
        )
    )
    replay.append(
        run(
            "unknown torrent rejected",
            "have before metainfo is invalid",
            [{"bt": "have", "index": 0, "info_hash": digest, "peer": "bob"}],
        )
    )
    replay.append(
        run(
            "prototype limits",
            "name length and piece count are capped",
            [
                {"bt": "metainfo", "name": "x" * 65, "pieces": ["0" * 64]},
                {"bt": "metainfo", "name": "ok", "pieces": ["0" * 64] * 65},
            ],
        )
    )
    return {
        **header(
            "bittorrent.swarm",
            "SPEC/features/bittorrent-swarm.md",
            "Pedagogical BitTorrent: metainfo, verified pieces, have-set.",
        ),
        "assembled": bytes("ABCDEFGHIJKL", "utf-8").hex(),
        "info_hash": digest,
        "length": seed["length"],
        "name": "demo",
        "payload": "ABCDEFGHIJKL",
        "piece_size": 4,
        "pieces": seed["pieces"],
        "replay": replay,
    }


def discovery_nat_vectors() -> Dict[str, Any]:
    txid = "0102030405060708090a0b0c"
    mapped_host = "203.0.113.5"
    mapped_port = 9735
    success = binding_success(txid, mapped_host, mapped_port)
    assert success["ok"]

    def response_case(name: str, packet: str, ident: str = txid) -> Dict[str, Any]:
        parsed = parse_binding_response(packet, ident)
        return {
            "name": name,
            "packet": packet,
            "txid": ident,
            "ok": parsed["ok"],
            "host": parsed["host"],
            "port": parsed["port"],
        }

    raw = bytes.fromhex(success["packet"])
    bad_magic = bytearray(raw)
    bad_magic[4] ^= 0xFF
    short = raw[:10].hex()
    empty_attr = raw[:20]
    empty_attr = empty_attr[:2] + struct_length(0) + empty_attr[4:]
    unknown = prepend_attribute(raw, 0x8022, b"test")
    bad_family = stun_value(txid, bytes([0x00, 0x02, 0x00, 0x01, 0, 0, 0, 0]))
    port_zero = stun_value(txid, bytes([0x00, 0x01, 0x21, 0x12, 0, 0, 0, 0]))

    requests = []
    for name, ident in (
        ("binding request", txid),
        ("uppercase transaction id", txid.upper()),
        ("short transaction id", "0102"),
        ("empty transaction id", ""),
    ):
        produced = binding_request(ident)
        requests.append(
            {"name": name, "txid": ident, "ok": produced["ok"], "packet": produced["packet"]}
        )

    successes = []
    for name, host, port in (
        ("mapped", mapped_host, mapped_port),
        ("leading zero", "203.0.113.05", mapped_port),
        ("unicode octet", "203.0.113.١", mapped_port),
        ("port zero", mapped_host, 0),
        ("bool port", mapped_host, True),
    ):
        produced = binding_success(txid, host, port)
        successes.append(
            {
                "name": name,
                "txid": txid,
                "host": host,
                "port": port,
                "ok": produced["ok"],
                "packet": produced["packet"],
            }
        )

    responses = [
        response_case("xor-mapped address", success["packet"]),
        response_case("unknown attribute ignored", unknown),
        response_case("wrong transaction id", success["packet"], "ffffffffffffffffffffffff"),
        response_case("bad magic", bad_magic.hex()),
        response_case("truncated", short),
        response_case("no attribute", empty_attr.hex()),
        response_case("ipv6 family", bad_family),
        response_case("port zero", port_zero),
        response_case("uppercase packet", success["packet"].upper()),
    ]

    def play(
        name: str, description: str, listen: str, ops: List[Dict[str, Any]], external: Any = None, relay: Any = None
    ) -> Dict[str, Any]:
        node = NatTraversal(listen, external=external, relay=relay)
        steps = []
        for op in ops:
            result = _nat_step(node, op)
            steps.append(
                {
                    **op,
                    **result,
                    "advertise": node.advertise(),
                    "armed": node.armed(),
                    "external": node.external_address(),
                    "opened": node.opened(),
                }
            )
        return {
            "name": name,
            "description": description,
            "listen": listen,
            "external": external,
            "relay": relay,
            "steps": steps,
        }

    packet = success["packet"]
    request = {
        "extra": 1,
        "from": "198.51.100.10:4000",
        "nat": "request",
        "relay": "127.0.0.1:3478",
        "target": "203.0.113.5:9735",
    }
    response = {
        "from": "198.51.100.10:4000",
        "nat": "response",
        "target": "203.0.113.5:9735",
    }
    sequence = [
        play(
            "stun then punch",
            "arm, learn a mapping, punch, observe the sentinel",
            "127.0.0.1:9735",
            [
                {"op": "arm", "transport": "tcp"},
                {"op": "observe_stun", "packet": packet, "txid": txid},
                {"op": "arm", "transport": "UDP"},
                {"op": "arm", "transport": "udp"},
                {"op": "observe_stun", "packet": packet, "txid": txid},
                {"op": "punch", "peer": "198.51.100.10:4000"},
                {"op": "punch", "peer": "127.0.0.1:9735"},
                {"op": "punch", "peer": "203.0.113.5:9735"},
                {"op": "observe_punch", "datagram": "00", "from": "198.51.100.10:4000"},
                {"op": "observe_punch", "datagram": "00", "from": "198.51.100.10:4000"},
                {"op": "observe_punch", "datagram": "01", "from": "198.51.100.20:4001"},
            ],
        ),
        play(
            "external skips stun",
            "a configured external address is not replaced",
            "10.0.0.2:9735",
            [
                {"op": "arm", "transport": "udp"},
                {"op": "observe_stun", "packet": packet, "txid": txid},
                {"op": "punch", "peer": "198.51.100.10:4000"},
            ],
            external="203.0.113.5:9735",
        ),
        play(
            "relay introduction",
            "request, duplicate, forward, and response",
            "127.0.0.1:3478",
            [
                {"op": "relay_request", "target": "198.51.100.10:4000"},
                {"op": "arm", "transport": "udp"},
                {"op": "handle", "message": "nope"},
                {"op": "relay_request", "target": "198.51.100.10:4000"},
                {"op": "relay_request", "target": "127.0.0.1:3478"},
                {"op": "handle", "message": request},
                {"op": "handle", "message": request},
                {"op": "handle", "message": response},
            ],
            relay="10.0.0.9:3478",
        ),
        play(
            "forward and accept",
            "relay forwards a request; the mapped node accepts the response",
            "10.0.0.8:3478",
            [
                {"op": "arm", "transport": "udp"},
                {"op": "observe_stun", "packet": packet, "txid": txid},
                {
                    "op": "handle",
                    "message": {
                        "from": "10.0.0.2:9735",
                        "nat": "request",
                        "relay": "203.0.113.5:9735",
                        "target": "198.51.100.10:4000",
                    },
                },
                {"op": "handle", "message": response},
                {"op": "relay_request", "target": "198.51.100.10:4000"},
            ],
        ),
    ]

    construct = []
    for name, listen, external, relay in (
        ("listen only", "127.0.0.1:9735", None, None),
        ("with external and relay", "10.0.0.2:1", "203.0.113.5:9735", "10.0.0.9:3478"),
        ("bad listen", "nope", None, None),
        ("empty external", "127.0.0.1:1", "", None),
        ("bad relay", "127.0.0.1:1", None, "10.0.0.1"),
    ):
        try:
            node = NatTraversal(listen, external=external, relay=relay)
        except ProtocolError:
            construct.append(
                {
                    "name": name,
                    "listen": listen,
                    "external": external,
                    "relay": relay,
                    "ok": False,
                    "advertise": "",
                }
            )
        else:
            construct.append(
                {
                    "name": name,
                    "listen": listen,
                    "external": external,
                    "relay": relay,
                    "ok": True,
                    "advertise": node.advertise(),
                }
            )

    return {
        **header(
            "discovery.nat",
            "SPEC/features/discovery-nat.md",
            "STUN binding, one-byte hole punch, and an app.nat relay.",
        ),
        "app_type": "app.nat",
        "punch": "00",
        "request": requests,
        "success": successes,
        "response": responses,
        "construct": construct,
        "sequence": sequence,
    }


def _nat_step(node: NatTraversal, op: Dict[str, Any]) -> Dict[str, Any]:
    name = op["op"]
    if name == "arm":
        return {"ok": node.arm(op["transport"])}
    if name == "observe_stun":
        return {"ok": node.observe_stun(op["packet"], op["txid"])}
    if name == "punch":
        return node.punch(op["peer"])
    if name == "observe_punch":
        return {"ok": node.observe_punch(op["datagram"], op["from"])}
    if name == "relay_request":
        return node.relay_request(op["target"])
    if name == "handle":
        return node.handle(op["message"])
    raise AssertionError(name)


def struct_length(length: int) -> bytes:
    import struct

    return struct.pack(">H", length)


def prepend_attribute(packet: bytes, atype: int, value: bytes) -> str:
    import struct

    attr = struct.pack(">HH", atype, len(value)) + value
    length = struct.unpack(">H", packet[2:4])[0] + len(attr)
    header = packet[:2] + struct.pack(">H", length) + packet[4:20]
    return (header + attr + packet[20:]).hex()


def stun_value(txid: str, value: bytes) -> str:
    import struct

    attr = struct.pack(">HH", 0x0020, len(value)) + value
    header = struct.pack(">HHI", 0x0101, len(attr), 0x2112A442) + bytes.fromhex(txid)
    return (header + attr).hex()


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
    print("\nLevel 2 — crypto primitives")
    write("ecdsa.json", ecdsa_vectors())
    write("vdf.json", vdf_vectors())
    write("vrf.json", vrf_vectors())
    print("\nLevel 2 — discovery")
    write("discovery-peer.json", discovery_peer_vectors())
    write("discovery-local.json", discovery_local_vectors())
    print("\nLevel 2 — consensus")
    write("consensus-pow.json", consensus_pow_vectors())
    write("consensus-pos.json", consensus_pos_vectors())
    write("consensus-pbft.json", consensus_pbft_vectors())
    print("\nLevel 2 — ledgers")
    write("ledger-balance.json", ledger_balance_vectors())
    write("ledger-utxo.json", ledger_utxo_vectors())
    print("\nLevel 2 — mempool and fees")
    write("mempool-basic.json", mempool_basic_vectors())
    write("fees-policy.json", fees_policy_vectors())
    print("\nLevel 2 — storage and CLI")
    write("storage-persistent.json", storage_persistent_vectors())
    write("cli-node.json", cli_node_vectors())
    print("\nLevel 2 — BitTorrent swarm")
    write("bittorrent-swarm.json", bittorrent_swarm_vectors())
    print("\nLevel 2 — NAT traversal")
    write("discovery-nat.json", discovery_nat_vectors())
    print(f"\nWritten to {VECTORS.relative_to(REPO)}")
    print("A diff here means the wire protocol changed. See AGENTS.md section 7.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
