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
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "python"))
# The Level 1 fixture objects live under tests/ because they are conformance
# scaffolding, not shipped API. See SPEC/semantics-v1.md section 8.
sys.path.insert(0, str(REPO / "python" / "tests"))

from chaincraft import (  # noqa: E402
    adapters,
    channel,
    control,
    crypto,
    discovery,
    ecdsa,
    framing,
    vdf,
    vrf,
)
from chaincraft.consensus_avalanche import Avalanche  # noqa: E402
from chaincraft.consensus_pbft import PBFT  # noqa: E402
from chaincraft.consensus_pos import ProofOfStake, proposer_for  # noqa: E402
from chaincraft.consensus_beacon import (  # noqa: E402
    GENESIS_PREVIOUS,
    RandomnessBeacon,
    pulse_id as beacon_pulse_id,
)
from chaincraft.consensus_poet import (  # noqa: E402
    ProofOfElapsedTime,
    ticket_id as poet_ticket_id,
)
from chaincraft.consensus_ouroboros import (  # noqa: E402
    Ouroboros,
    block_id as ouroboros_block_id,
    epoch_of as ouroboros_epoch_of,
)
from chaincraft.consensus_poa import (  # noqa: E402
    ProofOfAuthority,
    block_id as poa_block_id,
    proposer_for as poa_proposer_for,
)
from chaincraft.consensus_pox import (  # noqa: E402
    ProofOfTransfer,
    bid_id as pox_bid_id,
    sortition_score as pox_sortition_score,
    stack_id as pox_stack_id,
    tenure_id as pox_tenure_id,
)
from chaincraft.ban import BanSet, classify_inbound  # noqa: E402
from chaincraft.consensus_pow import ProofOfWork, block_id, mine  # noqa: E402
from chaincraft.crdt import MAX_KEYS, CrdtKv  # noqa: E402
from chaincraft.fees import charge, estimate, next_base_fee, select  # noqa: E402
from chaincraft.ledger_balance import BalanceLedger  # noqa: E402
from chaincraft.pubsub import MAX_MEMBERS, MAX_POSTS, MAX_ROOMS, MAX_TEXT, PubSub  # noqa: E402
from chaincraft.stream import (  # noqa: E402
    MAX_BATCH,
    MAX_BROKERS,
    MAX_EVENTS,
    MAX_GROUPS,
    MAX_PARTITIONS,
    MAX_PAYLOAD,
    MAX_PRODUCERS,
    MAX_STREAMS,
    Stream,
)
from chaincraft.ledger_utxo import UtxoLedger, transaction_id  # noqa: E402
from chaincraft.bittorrent import Swarm, split_payload  # noqa: E402
from chaincraft.envelope import ProtocolError  # noqa: E402
from chaincraft.nat import (  # noqa: E402
    NatTraversal,
    binding_request,
    binding_success,
    parse_binding_response,
)
from chaincraft.cli import NodeSession  # noqa: E402
from chaincraft.mempool import Mempool, transaction_id as mempool_tx_id  # noqa: E402
from chaincraft.storage import MessageStore  # noqa: E402
from chaincraft.canonical import (  # noqa: E402
    MAX_SAFE_INT,
    canonical_json,
    parse_json,
    payload_digest,
)
from chaincraft.dedup import DEFAULT_CAPACITY, Deduplicator  # noqa: E402
from chaincraft.envelope import Envelope  # noqa: E402
from chaincraft.memento import StateMemento  # noqa: E402
from chaincraft.object import frontier_digest, merkle_digest, wins_replacement  # noqa: E402
from conformance_objects import build_registry, snapshot  # noqa: E402

VECTORS = REPO / "conformance" / "vectors"

TS = 1757430000000  # fixed reference timestamp for every generated envelope
NOW = 1757430000000
SECKEY = bytes.fromhex(
    "0000000000000000000000000000000000000000000000000000000000000003"
)
SECKEY_B = bytes.fromhex(
    "c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721"
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
        ("unicode hostname", "é.local:1"),
        ("unicode ipv4 octet", "127.0.0.١:1"),
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
            "no-evict ingest, code-point advertise, injected clock. "
            "Connect allows public unicast IPv4 and DNS names.",
        ),
        "now_ms": NOW,
        "default_capacity": discovery.DEFAULT_CAPACITY,
        "default_timeout_ms": discovery.DEFAULT_TIMEOUT_MS,
        "valid": [{"name": addr, "address": addr} for addr in valid],
        "invalid": [{"name": name, "address": addr} for name, addr in invalid],
        "connect": [
            {"name": name, "address": addr, "allowed": discovery.is_connect_allowed(addr)}
            for name, addr in [
                ("loopback", "127.0.0.1:21000"),
                ("rfc1918", "10.0.0.2:9735"),
                ("public ipv4", "8.8.8.8:53"),
                ("public hostname", "example.com:443"),
                ("localhost", "localhost:9735"),
                ("mdns", "node-a.local:8080"),
                ("unspecified", "0.0.0.0:21000"),
                ("link local", "169.254.169.254:80"),
                ("multicast", "224.0.0.1:9735"),
            ]
        ],
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


def _ban_state(bs: BanSet, now_ms: int) -> Dict[str, Any]:
    state = bs.state(now_ms)
    return {
        "size": state["size"],
        "banned": state["banned"],
        "tracked": state["tracked"],
    }


def discovery_ban_vectors() -> Dict[str, Any]:
    base = 1757430000000
    peer_a = "10.0.0.2:9735"
    peer_b = "10.0.0.3:9735"
    bad_peer = "not-an-address"

    def run(
        name: str,
        note: str,
        strike_limit: int = 3,
        ban_ttl_ms: int = 60_000,
        ops: List[Dict[str, Any]] | None = None,
        classify: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        bs = BanSet(strike_limit=strike_limit, ban_ttl_ms=ban_ttl_ms)
        steps: List[Dict[str, Any]] = []
        for op in ops or []:
            kind = op["op"]
            clock = op.get("now_ms", base)
            if kind == "note":
                result = bs.note(op["peer"], op["reason"], clock)
                step = {
                    "op": "note",
                    "peer": op["peer"],
                    "reason": op["reason"],
                    "now_ms": clock,
                    "result": result,
                    "strikes": bs.strikes(op["peer"]),
                }
            elif kind == "strikes":
                step = {
                    "op": "strikes",
                    "peer": op["peer"],
                    "strikes": bs.strikes(op["peer"]),
                }
            elif kind == "banned":
                step = {"op": "banned", "now_ms": clock, "banned": bs.banned(clock)}
            elif kind == "is_banned":
                step = {
                    "op": "is_banned",
                    "peer": op["peer"],
                    "now_ms": clock,
                    "banned": bs.is_banned(op["peer"], clock),
                }
            else:
                raise ValueError(kind)
            step.update(_ban_state(bs, op.get("now_ms", base)))
            steps.append(step)
        classification = []
        for row in classify or []:
            out = classify_inbound(
                row["type"],
                row["solicited"],
                row["duplicate"],
                row["address_ok"],
            )
            classification.append({**row, **out})
            classification[-1].update(_ban_state(bs, base))
        return {
            "name": name,
            "note": note,
            "strike_limit": strike_limit,
            "ban_ttl_ms": ban_ttl_ms,
            "steps": steps,
            "classify": classification,
        }

    peers64 = [f"10.0.0.{index}:9735" for index in range(2, 66)]
    cap_evict_ops = [
        {"op": "note", "peer": peer, "reason": "digest_flood"} for peer in peers64
    ] + [{"op": "note", "peer": "10.0.1.1:9735", "reason": "digest_flood"}]
    fill_ops = [
        {
            "op": "note",
            "peer": peer,
            "reason": "invalid_address",
            "now_ms": base + index,
        }
        for index, peer in enumerate(peers64)
    ]
    sequence = [
        run(
            "three digest_flood strikes ban",
            "third note is banned with three strikes",
            ops=[
                {"op": "note", "peer": peer_a, "reason": "digest_flood"},
                {"op": "note", "peer": peer_a, "reason": "digest_flood"},
                {"op": "note", "peer": peer_a, "reason": "digest_flood"},
                {"op": "strikes", "peer": peer_a},
                {"op": "banned", "now_ms": base},
            ],
        ),
        run(
            "strike_limit one",
            "first digest_flood bans immediately",
            strike_limit=1,
            ops=[
                {"op": "note", "peer": peer_a, "reason": "digest_flood"},
                {"op": "strikes", "peer": peer_a},
            ],
        ),
        run(
            "invalid_address immediate ban",
            "one strike reason bans on first call",
            ops=[{"op": "note", "peer": peer_a, "reason": "invalid_address"}],
        ),
        run(
            "malformed counts as flood",
            "malformed adds a strike like digest_flood",
            ops=[
                {"op": "note", "peer": peer_a, "reason": "malformed"},
                {"op": "strikes", "peer": peer_a},
            ],
        ),
        run(
            "ignored invalid inputs",
            "unknown reason and bad peer leave strikes at zero",
            ops=[
                {"op": "note", "peer": peer_a, "reason": "unknown"},
                {"op": "note", "peer": bad_peer, "reason": "digest_flood"},
                {"op": "note", "peer": peer_a, "reason": "digest_flood", "now_ms": True},
                {"op": "note", "peer": peer_a, "reason": "digest_flood", "now_ms": -1},
                {"op": "strikes", "peer": peer_a},
            ],
        ),
        run(
            "ban ttl and repeat note",
            "banned_at fixed until expiry clears strikes",
            ops=[
                {"op": "note", "peer": peer_a, "reason": "invalid_address"},
                {"op": "note", "peer": peer_a, "reason": "digest_flood", "now_ms": base + 1000},
                {"op": "is_banned", "peer": peer_a, "now_ms": base + 60_000},
                {"op": "is_banned", "peer": peer_a, "now_ms": base + 60_001},
                {"op": "strikes", "peer": peer_a},
            ],
        ),
        run(
            "65th peer evicts oldest non-banned",
            "one strike per slot then one more peer",
            ops=cap_evict_ops,
        ),
        run(
            "full ban set ignores new peer",
            "64 active bans block tracking a new peer",
            ops=fill_ops
            + [
                {
                    "op": "note",
                    "peer": "10.0.1.1:9735",
                    "reason": "digest_flood",
                    "now_ms": base + 200,
                },
            ],
        ),
        run(
            "classify_inbound rows",
            "unsolicited ctl.peers does not touch the ban set",
            classify=[
                {
                    "type": "ctl.peers",
                    "solicited": False,
                    "duplicate": False,
                    "address_ok": True,
                },
                {
                    "type": "ctl.peers",
                    "solicited": True,
                    "duplicate": False,
                    "address_ok": True,
                },
                {"type": "link.ping", "solicited": False, "duplicate": False, "address_ok": True},
                {
                    "type": "app.counter",
                    "solicited": False,
                    "duplicate": False,
                    "address_ok": False,
                },
                {
                    "type": "app.counter",
                    "solicited": False,
                    "duplicate": True,
                    "address_ok": True,
                },
                {
                    "type": "app.counter",
                    "solicited": False,
                    "duplicate": False,
                    "address_ok": True,
                },
            ],
        ),
        run(
            "banned sort order",
            "banned list is code-point sorted",
            ops=[
                {"op": "note", "peer": "10.0.0.10:9735", "reason": "invalid_address"},
                {"op": "note", "peer": "10.0.0.2:9735", "reason": "invalid_address"},
                {"op": "note", "peer": "10.0.0.3:9735", "reason": "invalid_address"},
                {"op": "banned", "now_ms": base},
            ],
        ),
    ]

    return {
        **header(
            "discovery.ban",
            "SPEC/features/discovery-ban.md",
            "Local strike list with ban TTL and mesh allow_peer gate.",
        ),
        "now_ms": base,
        "sequence": sequence,
    }


def _message_json(message: Any) -> str:
    try:
        return canonical_json(message)
    except Exception:
        return json.dumps(message, sort_keys=True, separators=(",", ":"))


def _replay_object(name: str, factory, messages: List[Any]) -> Dict[str, Any]:
    obj = factory()
    steps = []
    for message in messages:
        accepted = obj.is_valid(message)
        if accepted:
            obj.add_message(message)
        steps.append(
            {
                "message_json": _message_json(message),
                "accepted": accepted,
                **obj.state(),
            }
        )
    return {"name": name, "steps": steps}


def _extend(parent: str, height: int, miner: str, prefix: str, count: int, difficulty: int) -> List[Dict[str, Any]]:
    blocks = []
    for index in range(count):
        block = mine(parent, height + index, miner, f"{prefix}-{index}", difficulty)
        blocks.append(block)
        parent = block["id"]
    return blocks


def _replay_reorgs(difficulty: int) -> Dict[str, Any]:
    """Two successive reorgs, each dropping more than one canonical block."""
    genesis = mine("", 1, "alice", "genesis", difficulty)
    main = _extend(genesis["id"], 2, "alice", "main", 3, difficulty)
    side = _extend(genesis["id"], 2, "bob", "side", 4, difficulty)
    resumed = _extend(main[-1]["id"], 5, "alice", "resume", 2, difficulty)
    lost = mine(genesis["id"], 2, "carol", "lost", difficulty)
    messages = [genesis, *main, *side, *resumed, lost]
    obj = ProofOfWork(difficulty)
    steps = []
    previous: List[str] = []
    prev_tip = ""
    for message in messages:
        accepted = obj.is_valid(message)
        if accepted:
            obj.add_message(message)
        state = obj.state()
        canon = state["canonical"]
        shared = 0
        while shared < len(previous) and shared < len(canon) and previous[shared] == canon[shared]:
            shared += 1
        reorg = bool(prev_tip) and prev_tip not in canon
        steps.append(
            {
                "message_json": canonical_json(message),
                "accepted": accepted,
                "reorg": reorg,
                "reorg_depth": (len(previous) - shared) if reorg else 0,
                **state,
            }
        )
        previous = list(canon)
        prev_tip = state["tip"]
    depths = [step["reorg_depth"] for step in steps if step["reorg"]]
    if len(depths) != 2 or min(depths) < 3:
        raise AssertionError(f"reorg scenario drifted: {depths}")
    return {
        "name": "two multi-block reorgs",
        "min_reorg_depth": 3,
        "reorg_count": 2,
        "steps": steps,
    }


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
        _replay_reorgs(difficulty),
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


POET_SEED = "poet-round"


def _poet_ticket(author: str, payload: str, wait: int) -> Dict[str, Any]:
    seed = POET_SEED.encode("utf-8")
    proof = vdf.proof_to_hex(vdf.evaluate(seed, wait))
    return {
        "author": author,
        "consensus": "poet",
        "payload": payload,
        "proof": proof,
        "wait": wait,
    }


def _replay_poet(name: str, factory, messages: List[Any], track_reorg: bool = False) -> Dict[str, Any]:
    obj = factory()
    steps = []
    previous: List[str] = []
    prev_winner = ""
    for message in messages:
        accepted = obj.is_valid(message)
        if accepted:
            obj.add_message(message)
        state = obj.state()
        step = {
            "message_json": canonical_json(message),
            "accepted": accepted,
            **state,
        }
        if track_reorg:
            canon = state["canonical"]
            shared = 0
            while shared < len(previous) and shared < len(canon) and previous[shared] == canon[shared]:
                shared += 1
            reorg = bool(prev_winner) and prev_winner not in canon
            step["reorg"] = reorg
            step["reorg_depth"] = (len(previous) - shared) if reorg else 0
            previous = list(canon)
            prev_winner = state["winner"]
        steps.append(step)
    return {"name": name, "steps": steps}


def consensus_poet_vectors() -> Dict[str, Any]:
    alice = _poet_ticket("alice", "one", 2)
    bob = _poet_ticket("bob", "two", 1)
    carol = _poet_ticket("carol", "three", 2)
    dave = _poet_ticket("dave", "four", 2)
    erin = _poet_ticket("erin", "five", 3)
    bob_proof = bob["proof"]
    factory = lambda: ProofOfElapsedTime(POET_SEED)  # noqa: E731
    replay = [
        _replay_poet(
            "shortest wait replaces winner",
            factory,
            [alice, bob, erin],
            track_reorg=True,
        ),
        _replay_poet(
            "equal wait lowest id wins",
            factory,
            [alice, dave, carol],
            track_reorg=True,
        ),
        _replay_poet("duplicate ticket rejected", factory, [alice, alice]),
        _replay_poet(
            "rejection pins",
            factory,
            [
                {**alice, "wait": 0},
                {**alice, "wait": True},
                {**alice, "wait": 4_294_967_296},
                {**alice, "author": ""},
                {**alice, "payload": ""},
                {**alice, "consensus": "poa"},
                {**alice, "proof": "1"},
                {**bob, "wait": 2},
                {**bob, "proof": bob_proof.upper()},
                {**bob, "proof": "0" + bob_proof},
            ],
        ),
    ]
    alice_id = poet_ticket_id("alice", "one", alice["proof"], 2)
    bob_id = poet_ticket_id("bob", "two", bob["proof"], 1)
    return {
        **header(
            "consensus.poet",
            "SPEC/features/consensus-poet.md",
            "PoET object: shortest Sloth wait wins; equal wait breaks to lowest id.",
        ),
        "seed": POET_SEED,
        "alice_id": alice_id,
        "bob_id": bob_id,
        "replay": replay,
    }


def _beacon_vrf_message(height: int, previous: str) -> bytes:
    return canonical_json({"height": height, "previous": previous}).encode("utf-8")


def _beacon_pulse(sk: bytes, height: int, previous: str) -> Dict[str, Any]:
    message = _beacon_vrf_message(height, previous)
    proof, output, pk = vrf.evaluate(message, sk)
    return {
        "consensus": "beacon",
        "height": height,
        "previous": previous,
        "pk": pk.hex(),
        "proof": proof.hex(),
        "output": output.hex(),
    }


def _replay_beacon(name: str, factory, messages: List[Any]) -> Dict[str, Any]:
    obj = factory()
    steps = []
    for message in messages:
        accepted = obj.is_valid(message)
        if accepted:
            obj.add_message(message)
        state = obj.state()
        steps.append(
            {
                "message_json": canonical_json(message),
                "accepted": accepted,
                **state,
            }
        )
    return {"name": name, "steps": steps}


def consensus_beacon_vectors() -> Dict[str, Any]:
    genesis = _beacon_pulse(SECKEY, 0, GENESIS_PREVIOUS)
    genesis_output = genesis["output"]
    height1 = _beacon_pulse(SECKEY_B, 1, genesis_output)
    wrong_height = _beacon_pulse(SECKEY_B, 2, genesis_output)
    bad_previous = _beacon_pulse(SECKEY_B, 1, "f" * 64)
    bad_proof = {**height1, "proof": "f" * 128}
    swapped_output = {**height1, "output": "a" * 64}
    alt_genesis = _beacon_pulse(SECKEY_B, 0, GENESIS_PREVIOUS)
    factory = lambda: RandomnessBeacon()  # noqa: E731
    replay = [
        _replay_beacon("chained genesis and extension", factory, [genesis, height1]),
        _replay_beacon("wrong height rejected", factory, [genesis, wrong_height]),
        _replay_beacon("wrong previous rejected", factory, [genesis, bad_previous]),
        _replay_beacon(
            "vrf failure rejected",
            factory,
            [genesis, bad_proof, swapped_output],
        ),
        _replay_beacon(
            "duplicate and competing genesis rejected",
            factory,
            [genesis, genesis, alt_genesis],
        ),
        _replay_beacon(
            "malformed pulses rejected",
            factory,
            [
                {**genesis, "height": True},
                {**genesis, "previous": genesis["previous"].upper()},
                {**genesis, "consensus": "poet"},
            ],
        ),
    ]
    genesis_id = beacon_pulse_id(
        genesis["height"],
        genesis["output"],
        genesis["pk"],
        genesis["previous"],
        genesis["proof"],
    )
    return {
        **header(
            "consensus.beacon",
            "SPEC/features/consensus-beacon.md",
            "Chained VRF beacon; next height must cite the previous output.",
        ),
        "genesis_id": genesis_id,
        "replay": replay,
    }


OURO_NONCE = "0123456789abcdef" * 4
OURO_EPOCH_LENGTH = 2
OURO_KEYS = {"alice": SECKEY, "bob": SECKEY_B}


def _ouro_stakeholder_table() -> List[Tuple[str, int, str]]:
    rows: List[Tuple[str, int, str]] = []
    for sid, stake, sk in [("alice", 100, SECKEY), ("bob", 1, SECKEY_B)]:
        pk = vrf.evaluate(b"bootstrap", sk)[2].hex()
        rows.append((sid, stake, pk))
    return rows


def _ouro_factory() -> Ouroboros:
    return Ouroboros(OURO_NONCE, OURO_EPOCH_LENGTH, _ouro_stakeholder_table())


def _ouro_block(
    prior: List[Dict[str, Any]],
    parent_id: str,
    slot: int,
    payload: str,
    leader: str,
) -> Dict[str, Any]:
    obj = Ouroboros(OURO_NONCE, OURO_EPOCH_LENGTH, _ouro_stakeholder_table())
    for message in prior:
        obj.add_message(message)
    parent_record = obj._blocks.get(parent_id) if parent_id else None
    epoch, epoch_nonce = obj._epoch_nonce_for_slot(slot, parent_record)
    sk = OURO_KEYS[leader]
    vrf_message = obj._vrf_message(epoch, epoch_nonce, slot, leader)
    proof, output, pk = vrf.evaluate(vrf_message, sk)
    return {
        "consensus": "ouroboros",
        "slot": slot,
        "parent": parent_id,
        "payload": payload,
        "leader": leader,
        "pk": pk.hex(),
        "proof": proof.hex(),
        "output": output.hex(),
    }


def _replay_ouro(
    name: str, factory, messages: List[Any], track_reorg: bool = False
) -> Dict[str, Any]:
    obj = factory()
    steps = []
    previous: List[str] = []
    prev_tip = ""
    for message in messages:
        accepted = obj.is_valid(message)
        if accepted:
            obj.add_message(message)
        state = obj.state()
        step = {
            "message_json": canonical_json(message),
            "accepted": accepted,
            **state,
        }
        if track_reorg:
            canon = state["canonical"]
            shared = 0
            while (
                shared < len(previous)
                and shared < len(canon)
                and previous[shared] == canon[shared]
            ):
                shared += 1
            reorg = bool(prev_tip) and prev_tip not in canon
            step["reorg"] = reorg
            step["reorg_depth"] = (len(previous) - shared) if reorg else 0
            previous = list(canon)
            prev_tip = state["tip"]
        steps.append(step)
    result = {"name": name, "steps": steps}
    if track_reorg:
        depths = [step["reorg_depth"] for step in steps if step["reorg"]]
        if depths:
            result["reorg_count"] = len(depths)
            result["min_reorg_depth"] = min(depths)
    return result


def consensus_ouroboros_vectors() -> Dict[str, Any]:
    prior: List[Dict[str, Any]] = []
    slot1 = _ouro_block(prior, "", 1, "one", "alice")
    prior = [slot1]
    bob_fail = _ouro_block([], "", 1, "bob-only", "bob")
    slot2 = _ouro_block(prior, ouroboros_block_id(
        slot1["slot"],
        slot1["parent"],
        slot1["payload"],
        slot1["leader"],
        slot1["pk"],
        slot1["proof"],
        slot1["output"],
    ), 2, "two", "alice")
    s1_id = ouroboros_block_id(
        slot1["slot"],
        slot1["parent"],
        slot1["payload"],
        slot1["leader"],
        slot1["pk"],
        slot1["proof"],
        slot1["output"],
    )
    s2_id = ouroboros_block_id(
        slot2["slot"],
        slot2["parent"],
        slot2["payload"],
        slot2["leader"],
        slot2["pk"],
        slot2["proof"],
        slot2["output"],
    )
    prior2 = [slot1, slot2]
    slot3 = _ouro_block(prior2, s2_id, 3, "three", "alice")
    bad_epoch_nonce = _ouro_block(prior2, s2_id, 3, "wrong-nonce", "alice")
    msg = canonical_json(
        {
            "epoch": ouroboros_epoch_of(3, OURO_EPOCH_LENGTH),
            "nonce": OURO_NONCE,
            "slot": 3,
            "stakeholder": "alice",
        }
    ).encode("utf-8")
    proof, output, pk = vrf.evaluate(msg, SECKEY)
    bad_epoch_nonce["proof"] = proof.hex()
    bad_epoch_nonce["output"] = output.hex()
    bad_epoch_nonce["pk"] = slot3["pk"]
    bad_proof = {**slot1, "proof": "f" * 128}
    swapped_output = {**slot1, "output": "a" * 64}
    upper_hex = {**slot1, "pk": slot1["pk"].upper()}
    bool_slot = {**slot1, "slot": True}
    wrong_consensus = {**slot1, "consensus": "poa"}
    unknown_leader = {**slot1, "leader": "eve"}
    wrong_pk = {**slot1, "pk": bob_fail["pk"]}
    dup = slot1
    skip_parent = _ouro_block(prior2, s1_id, 3, "skip", "alice")
    bad_parent_genesis = {**slot1, "parent": "deadbeef"}
    alt_one = _ouro_block([], "", 1, "two", "alice")
    alt_two = _ouro_block(
        [alt_one],
        ouroboros_block_id(
            alt_one["slot"],
            alt_one["parent"],
            alt_one["payload"],
            alt_one["leader"],
            alt_one["pk"],
            alt_one["proof"],
            alt_one["output"],
        ),
        2,
        "fork-two",
        "alice",
    )
    factory = _ouro_factory
    replay = [
        _replay_ouro("eligible leader at slot 1", factory, [slot1]),
        _replay_ouro("non-leader rejected", factory, [bob_fail]),
        _replay_ouro("two-slot epoch-0 chain", factory, [slot1, slot2]),
        _replay_ouro(
            "epoch nonce from parent output at slot 3",
            factory,
            [slot1, slot2, slot3],
        ),
        _replay_ouro(
            "epoch-0 nonce at slot 3 rejected",
            factory,
            [slot1, slot2, bad_epoch_nonce],
        ),
        _replay_ouro(
            "bad vrf material rejected",
            factory,
            [bad_proof, swapped_output, upper_hex],
        ),
        _replay_ouro(
            "malformed fields rejected",
            factory,
            [bool_slot, wrong_consensus, unknown_leader, wrong_pk],
        ),
        _replay_ouro("duplicate id rejected", factory, [slot1, dup]),
        _replay_ouro(
            "parent height mismatch rejected",
            factory,
            [slot1, slot2, skip_parent, bad_parent_genesis],
        ),
        _replay_ouro(
            "two payloads same slot lower id is tip",
            factory,
            [slot1, alt_one],
        ),
        _replay_ouro(
            "fork overtakes tip",
            factory,
            [slot1, alt_one, alt_two],
            track_reorg=True,
        ),
        _replay_ouro(
            "extra keys ignored",
            factory,
            [{**slot1, "note": "ok"}],
        ),
    ]
    stakeholders = [
        {"id": sid, "stake": stake, "pk": pk}
        for sid, stake, pk in _ouro_stakeholder_table()
    ]
    return {
        **header(
            "consensus.ouroboros",
            "SPEC/features/consensus-ouroboros.md",
            "Ouroboros object: stake-weighted VRF slot leaders, longest chain.",
        ),
        "epoch_length": OURO_EPOCH_LENGTH,
        "nonce": OURO_NONCE,
        "stakeholders": stakeholders,
        "slot1_id": s1_id,
        "slot2_id": s2_id,
        "replay": replay,
    }


POA_AUTHORITIES = ["alice", "bob", "carol"]


def _poa_message(height: int, parent: str, payload: str) -> Dict[str, Any]:
    proposer = poa_proposer_for(height, POA_AUTHORITIES)
    return {
        "consensus": "poa",
        "height": height,
        "parent": parent,
        "payload": payload,
        "proposer": proposer,
    }


def _poa_chain(parent: str, start_height: int, payloads: List[str]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    cursor = parent
    height = start_height
    for payload in payloads:
        message = _poa_message(height, cursor, payload)
        blocks.append(message)
        cursor = poa_block_id(height, cursor, payload, message["proposer"])
        height += 1
    return blocks


def _replay_reorgs_poa() -> Dict[str, Any]:
    """Side chain overtakes main, then main extension becomes canonical again."""
    genesis = _poa_message(1, "", "genesis")
    genesis_id = poa_block_id(1, "", "genesis", "alice")
    main = _poa_chain(genesis_id, 2, ["main-2", "main-3"])
    main_tip = poa_block_id(3, poa_block_id(2, genesis_id, "main-2", "bob"), "main-3", "carol")
    side = _poa_chain(genesis_id, 2, ["side-2", "side-3", "side-4", "side-5"])
    resumed = _poa_chain(main_tip, 4, ["resume-4", "resume-5", "resume-6"])
    orphan = _poa_message(2, genesis_id, "lost")
    messages = [genesis, *main, *side, *resumed, orphan]
    factory = lambda: ProofOfAuthority(POA_AUTHORITIES)  # noqa: E731
    obj = factory()
    steps = []
    previous: List[str] = []
    prev_tip = ""
    for message in messages:
        accepted = obj.is_valid(message)
        if accepted:
            obj.add_message(message)
        state = obj.state()
        canon = state["canonical"]
        shared = 0
        while shared < len(previous) and shared < len(canon) and previous[shared] == canon[shared]:
            shared += 1
        reorg = bool(prev_tip) and prev_tip not in canon
        steps.append(
            {
                "message_json": canonical_json(message),
                "accepted": accepted,
                "reorg": reorg,
                "reorg_depth": (len(previous) - shared) if reorg else 0,
                **state,
            }
        )
        previous = list(canon)
        prev_tip = state["tip"]
    depths = [step["reorg_depth"] for step in steps if step["reorg"]]
    if len(depths) != 2 or min(depths) < 2:
        raise AssertionError(f"reorg scenario drifted: {depths}")
    return {
        "name": "multi-block reorg and recovery",
        "min_reorg_depth": 2,
        "reorg_count": 2,
        "steps": steps,
    }


POX_SEED = "0123456789abcdef" * 4
POX_CYCLE_LENGTH = 3
POX_STACKERS = [("alice", 100), ("bob", 200), ("carol", 50)]


def _pox_stack(locker: str, amount: int, reward_cycle: int) -> Dict[str, Any]:
    return {
        "consensus": "pox",
        "kind": "stack",
        "locker": locker,
        "amount": amount,
        "reward_cycle": reward_cycle,
    }


def _pox_bid(miner: str, btc_out: int, block_height: int) -> Dict[str, Any]:
    return {
        "consensus": "pox",
        "kind": "bid",
        "miner": miner,
        "btc_out": btc_out,
        "block_height": block_height,
    }


def _pox_tenure(winner: str, prev: str, block_height: int) -> Dict[str, Any]:
    return {
        "consensus": "pox",
        "kind": "tenure",
        "winner": winner,
        "prev": prev,
        "block_height": block_height,
    }


def _pox_factory() -> ProofOfTransfer:
    return ProofOfTransfer(POX_SEED, POX_CYCLE_LENGTH, POX_STACKERS)


def _pox_winning_tenure(obj: ProofOfTransfer, height: int) -> Dict[str, Any]:
    elected = obj._elected_miner(height)  # noqa: SLF001
    assert elected is not None
    tip, _ = obj._tip()  # noqa: SLF001
    prev = "" if height == 1 else tip
    return _pox_tenure(elected, prev, height)


def _pox_advance_three_blocks() -> List[Dict[str, Any]]:
    """Bid and tenure at heights 1..3 using the elected miner each time."""
    messages: List[Dict[str, Any]] = []
    probe = _pox_factory()
    for height in range(1, 4):
        for miner, btc in (("alice", 5), ("bob", 6), ("carol", 4)):
            bid = _pox_bid(miner, btc, height)
            if probe.is_valid(bid):
                messages.append(bid)
                probe.add_message(bid)
        messages.append(_pox_winning_tenure(probe, height))
        probe.add_message(messages[-1])
    return messages


def consensus_pox_vectors() -> Dict[str, Any]:
    bid_alice_h1 = _pox_bid("alice", 7, 1)
    tenure_alice_h1 = _pox_tenure("alice", "", 1)
    bid_bob_high = _pox_bid("bob", 99, 1)
    bid_alice_low = _pox_bid("alice", 1, 1)
    score_bob = pox_sortition_score(POX_SEED, "bob", 99, 1)
    score_alice = pox_sortition_score(POX_SEED, "alice", 1, 1)
    bid_alice_id = pox_bid_id("alice", 1, 1)
    bid_bob_id = pox_bid_id("bob", 99, 1)
    if score_alice < score_bob or (score_alice == score_bob and bid_alice_id < bid_bob_id):
        sortition_winner = "alice"
    else:
        sortition_winner = "bob"
    sortition_loser = "bob" if sortition_winner == "alice" else "alice"
    tenure_loser = _pox_tenure(sortition_loser, "", 1)
    bid_alice_dup = _pox_bid("alice", 8, 1)
    tenure_early = _pox_tenure("alice", "", 1)
    stack_open_cycle = _pox_stack("alice", 10, 1)
    stack_next = _pox_stack("dave", 15, 2)
    stack_dup = _pox_stack("dave", 20, 2)
    bid_dave_h1 = _pox_bid("dave", 3, 1)
    bid_bob_h4 = _pox_bid("bob", 3, 4)
    three_blocks = _pox_advance_three_blocks()
    factory = _pox_factory
    replay = [
        _replay_object(
            "tenure at height 1 after one bid",
            factory,
            [bid_alice_h1, tenure_alice_h1],
        ),
        _replay_object(
            "lower sortition score wins despite smaller btc_out",
            factory,
            [bid_bob_high, bid_alice_low, _pox_tenure(sortition_winner, "", 1)],
        ),
        _replay_object(
            "tenure naming loser rejected",
            factory,
            [bid_bob_high, bid_alice_low, tenure_loser],
        ),
        _replay_object(
            "bid from locker absent in cycle",
            factory,
            [bid_dave_h1],
        ),
        _replay_object(
            "second bid by same miner at height rejected",
            factory,
            [bid_alice_h1, bid_alice_dup],
        ),
        _replay_object(
            "tenure before any bid rejected",
            factory,
            [tenure_early],
        ),
        _replay_object(
            "stack for current open cycle rejected",
            factory,
            three_blocks + [stack_open_cycle],
        ),
        _replay_object(
            "stack next cycle then bid after boundary; cycle-0-only miner rejected",
            factory,
            [stack_next, *three_blocks, bid_bob_h4],
        ),
        _replay_object(
            "empty next-cycle snapshot rejects bids",
            factory,
            three_blocks + [_pox_bid("alice", 2, 4)],
        ),
        _replay_object(
            "duplicate stack locker for cycle rejected",
            factory,
            [stack_next, stack_dup],
        ),
        _replay_object(
            "boolean and float amounts rejected",
            factory,
            [
                {**_pox_stack("eve", 10, 2), "amount": True},
                {**_pox_stack("eve", 10, 2), "amount": 1.5},
            ],
        ),
        _replay_object(
            "consensus other than pox rejected",
            factory,
            [{**bid_alice_h1, "consensus": "pow"}],
        ),
        _replay_object(
            "duplicate id rejected",
            factory,
            [bid_alice_h1, bid_alice_h1],
        ),
        _replay_object(
            "extra keys ignored",
            factory,
            [{**bid_alice_h1, "note": "ok"}, tenure_alice_h1],
        ),
        _replay_object(
            "prev not equal to tip rejected",
            factory,
            [
                bid_alice_h1,
                tenure_alice_h1,
                _pox_bid("alice", 2, 2),
                {**_pox_tenure("alice", "", 2), "prev": "deadbeef"},
            ],
        ),
    ]
    return {
        **header(
            "consensus.pox",
            "SPEC/features/consensus-pox.md",
            "PoX object: stack cycles, bid sortition, tenure chain.",
        ),
        "seed": POX_SEED,
        "cycle_length": POX_CYCLE_LENGTH,
        "stackers": [{"locker": l, "amount": a} for l, a in POX_STACKERS],
        "sortition_winner_height_1": sortition_winner,
        "replay": replay,
    }


def consensus_poa_vectors() -> Dict[str, Any]:
    genesis_one = _poa_message(1, "", "one")
    genesis_id = poa_block_id(1, "", "one", "alice")
    chain_23 = _poa_chain(genesis_id, 2, ["two", "three"])
    wrong_proposer = {**genesis_one, "proposer": "dave"}
    alice_h2 = {**_poa_message(2, genesis_id, "skip"), "proposer": "alice"}
    bob_h2 = _poa_message(2, genesis_id, "two")
    fork_alt = _poa_message(1, "", "alt")
    alt_id = poa_block_id(1, "", "alt", "alice")
    factory = lambda: ProofOfAuthority(POA_AUTHORITIES)  # noqa: E731
    replay = [
        _replay_object("empty then three-block rotation", factory, [genesis_one, *chain_23]),
        _replay_object("wrong proposer at genesis", factory, [wrong_proposer]),
        _replay_object(
            "wrong turn then correct proposer",
            factory,
            [genesis_one, alice_h2, bob_h2],
        ),
        _replay_object("duplicate block rejected", factory, [genesis_one, genesis_one]),
        _replay_object(
            "same-height fork prefers lowest id",
            factory,
            [genesis_one, fork_alt],
        ),
        _replay_reorgs_poa(),
        _replay_object(
            "rejection pins",
            factory,
            [
                {**genesis_one, "height": 0},
                {**genesis_one, "payload": ""},
                {**_poa_message(2, "", "early")},
                {**_poa_message(2, "deadbeef", "orphan"), "proposer": "bob"},
                {**_poa_message(4, genesis_id, "skip"), "proposer": "alice"},
                {**genesis_one, "height": True},
            ],
        ),
    ]
    return {
        **header(
            "consensus.poa",
            "SPEC/features/consensus-poa.md",
            "PoA object: rotating authorities, longest tip, lowest-id tie-break.",
        ),
        "authorities": POA_AUTHORITIES,
        "genesis_one_id": genesis_id,
        "fork_alt_id": alt_id,
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


def consensus_avalanche_vectors() -> Dict[str, Any]:
    def init(color: str) -> Dict[str, Any]:
        return {"color": color, "consensus": "avalanche", "op": "init"}

    def round_of(*votes: str) -> Dict[str, Any]:
        return {"consensus": "avalanche", "op": "round", "votes": list(votes)}

    replay = [
        _replay_object(
            "slush adopts the sample",
            lambda: Avalanche("slush"),
            [init("blue"), round_of("red", "red"), round_of("blue", "red")],
        ),
        _replay_object(
            "snowflake finalizes after beta",
            lambda: Avalanche("snowflake"),
            [round_of("red", "red"), round_of("red", "red")],
        ),
        _replay_object(
            "snowflake reset on flip",
            lambda: Avalanche("snowflake"),
            [round_of("red", "red"), round_of("blue", "blue"), round_of("blue", "blue")],
        ),
        _replay_object(
            "snowball confidence and tie-break",
            lambda: Avalanche("snowball"),
            [round_of("red", "red"), round_of("blue", "blue")],
        ),
        _replay_object(
            "rejected round and second init",
            lambda: Avalanche("slush"),
            [init("red"), init("blue"), round_of("red")],
        ),
    ]
    return {
        **header(
            "consensus.avalanche",
            "SPEC/features/consensus-avalanche.md",
            "Slush, Snowflake, and Snowball with vector-pinned votes.",
        ),
        "alpha": 2,
        "beta": 2,
        "k": 2,
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


def storage_index_vectors() -> Dict[str, Any]:
    msg_type = "app.idx"
    field = "tag"

    def body(data: Dict[str, Any]) -> str:
        return Envelope.build(msg_type, data, ts=TS).to_json()

    a = payload_digest({"tag": "alpha"})
    b = payload_digest({"tag": "beta"})
    c = payload_digest({"tag": "gamma"})
    d = payload_digest({"tag": "delta", "n": 1})
    e = payload_digest({"tag": "mix", "tags": ["x", "y", "x"]})
    f = payload_digest({"tag": True})
    g = payload_digest({"tag": 1})
    h = payload_digest({"tag": "skip", "extra": {"nested": 1}})

    def run(name: str, note: str, capacity: int, ops) -> Dict[str, Any]:
        store = MessageStore(capacity)
        steps = []
        for op in ops:
            kind = op["op"]
            if kind == "register":
                ok = store.register(op["type"], op["field"])
                step = {
                    "op": "register",
                    "type": op["type"],
                    "field": op["field"],
                    "ok": ok,
                }
            elif kind == "put":
                added = store.put(op["id"], op["body"])
                step = {"op": "put", "id": op["id"], "body": op["body"], "added": added}
            elif kind == "query":
                hits = store.query(op["type"], op["field"], op["value"])
                step = {
                    "op": "query",
                    "type": op["type"],
                    "field": op["field"],
                    "value": op["value"],
                    "hits": hits,
                }
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

    bool_body = body({"tag": True})
    int_body = body({"tag": 1})
    float_skip = (
        f'{{"data":{{"tag":1.5}},"id":"{"0" * 64}","ts":{TS},"type":"{msg_type}","v":1}}'
    )
    obj_skip = body({"tag": "v", "bad": {"k": 1}})
    nested_arr = body({"tag": ["a", ["b"]]})
    dup_arr = body({"tag": ["p", "p", "q"]})

    snapshot = {
        "entries": [
            {"body": body({"tag": "loaded"}), "id": a},
            {"body": body({"tag": "two"}), "id": b},
        ],
        "v": 1,
    }
    bad_snapshot = {"entries": [{"body": "x", "id": a}, {"body": "y", "id": a}], "v": 1}

    sequence = [
        run(
            "register put query hit and miss",
            "equality on registered field",
            8,
            [
                {"op": "register", "type": msg_type, "field": field},
                {"op": "put", "id": a, "body": body({"tag": "alpha"})},
                {"op": "put", "id": b, "body": body({"tag": "beta"})},
                {
                    "op": "query",
                    "type": msg_type,
                    "field": field,
                    "value": "alpha",
                },
                {
                    "op": "query",
                    "type": msg_type,
                    "field": field,
                    "value": "missing",
                },
            ],
        ),
        run(
            "array elements and duplicate array values",
            "one id per put for duplicate index keys",
            8,
            [
                {"op": "register", "type": msg_type, "field": field},
                {"op": "put", "id": e, "body": dup_arr},
                {"op": "query", "type": msg_type, "field": field, "value": "p"},
                {"op": "query", "type": msg_type, "field": field, "value": "q"},
            ],
        ),
        run(
            "skip object float and nested array",
            "non-scalars are not indexed",
            8,
            [
                {"op": "register", "type": msg_type, "field": field},
                {"op": "put", "id": h, "body": obj_skip},
                {"op": "put", "id": d, "body": float_skip},
                {"op": "put", "id": c, "body": nested_arr},
                {"op": "query", "type": msg_type, "field": field, "value": "v"},
            ],
        ),
        run(
            "true does not match 1",
            "boolean and integer are distinct index keys",
            8,
            [
                {"op": "register", "type": msg_type, "field": field},
                {"op": "put", "id": f, "body": bool_body},
                {"op": "put", "id": g, "body": int_body},
                {"op": "query", "type": msg_type, "field": field, "value": True},
                {"op": "query", "type": msg_type, "field": field, "value": 1},
            ],
        ),
        run(
            "overwrite keeps insertion order",
            "replace body and index without moving id",
            8,
            [
                {"op": "register", "type": msg_type, "field": field},
                {"op": "put", "id": a, "body": body({"tag": "one"})},
                {"op": "put", "id": b, "body": body({"tag": "two"})},
                {"op": "put", "id": a, "body": body({"tag": "ONE"})},
                {"op": "query", "type": msg_type, "field": field, "value": "one"},
                {"op": "query", "type": msg_type, "field": field, "value": "ONE"},
            ],
        ),
        run(
            "fifo eviction drops index",
            "evicted id no longer appears in query",
            2,
            [
                {"op": "register", "type": msg_type, "field": field},
                {"op": "put", "id": a, "body": body({"tag": "first"})},
                {"op": "put", "id": b, "body": body({"tag": "second"})},
                {"op": "put", "id": c, "body": body({"tag": "third"})},
                {"op": "query", "type": msg_type, "field": field, "value": "first"},
            ],
        ),
        run(
            "remove drops index",
            "remove clears postings for that id",
            8,
            [
                {"op": "register", "type": msg_type, "field": field},
                {"op": "put", "id": a, "body": body({"tag": "gone"})},
                {"op": "remove", "id": a},
                {"op": "query", "type": msg_type, "field": field, "value": "gone"},
            ],
        ),
        run(
            "load rebuilds index; bad load leaves index",
            "successful load reindexes; failed load is a no-op",
            4,
            [
                {"op": "register", "type": msg_type, "field": field},
                {"op": "put", "id": c, "body": body({"tag": "before"})},
                {"op": "load", "snapshot": snapshot},
                {"op": "query", "type": msg_type, "field": field, "value": "loaded"},
                {"op": "load", "snapshot": bad_snapshot},
                {"op": "query", "type": msg_type, "field": field, "value": "loaded"},
            ],
        ),
        run(
            "query without registration is empty",
            "unregistered pair returns no hits",
            8,
            [
                {"op": "put", "id": a, "body": body({"tag": "orphan"})},
                {"op": "query", "type": msg_type, "field": field, "value": "orphan"},
            ],
        ),
    ]
    return {
        **header(
            "storage.index",
            "SPEC/features/storage-index.md",
            "Optional field index: register, put, query, eviction, load.",
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
        run(
            "channel uri",
            "connect accepts a parsed channel URI and rejects a bad one",
            [
                {"op": "start"},
                {
                    "op": "line",
                    "line": canonical_json(
                        {"addr": "webrtc:abcd", "cmd": "connect"}
                    ),
                },
                {
                    "op": "line",
                    "line": canonical_json(
                        {"addr": "udp://127.0.0.1:1", "cmd": "connect"}
                    ),
                },
                {
                    "op": "line",
                    "line": canonical_json(
                        {"addr": "webrtc:bad id", "cmd": "connect"}
                    ),
                },
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
            "Prototype BitTorrent: metainfo, verified pieces, have-set.",
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


def wire_channel_vectors() -> Dict[str, Any]:
    peer = "0" * 64
    parse_inputs = [
        ("bare loopback", "127.0.0.1:9735"),
        ("tcp uri", "tcp://127.0.0.1:9735"),
        ("udp lan", "udp://10.0.0.2:1"),
        ("hostname local", "node.local:9735"),
        ("mailto", "mailto:alice@example.com"),
        ("webrtc", f"webrtc:{peer}"),
        ("peerjs uuid", "webrtc:283e9542-cc0a-4301-8c37-70cd162fa2f8"),
        ("peerjs short", "webrtc:abcd"),
        ("forum", "forum:disc:t1"),
        ("loop", "loop:alice"),
        ("pipe", "pipe:alice"),
        ("empty", ""),
        ("uppercase scheme", "TCP://127.0.0.1:9735"),
        ("tcp without slashes", "tcp:127.0.0.1:9735"),
        ("path rejected", "tcp://127.0.0.1:9735/x"),
        ("query rejected", "tcp://127.0.0.1:9735?x=1"),
        ("bad ipv4", "256.0.0.1:9735"),
        ("unicode hostname", "tcp://é.local:1"),
        ("unicode ipv4 octet", "tcp://127.0.0.١:1"),
        ("leading zero port", "127.0.0.1:09735"),
        ("mailto missing at", "mailto:alice"),
        ("webrtc space", "webrtc:bad id"),
        ("webrtc too long", "webrtc:" + ("a" * 65)),
        ("webrtc dot", "webrtc:ab.cd"),
        ("forum extra colon", "forum:disc:t:1"),
        ("loop hyphen edge", "loop:-alice"),
        ("loop uppercase", "loop:Alice"),
        ("pipe hyphen edge", "pipe:-alice"),
        ("pipe uppercase", "pipe:Alice"),
    ]
    parse = []
    for name, raw in parse_inputs:
        parsed = channel.parse_address(raw)
        parse.append({"name": name, "input": raw, **parsed})

    connect_inputs = [
        ("loopback", "127.0.0.1:1"),
        ("tcp rfc1918", "tcp://10.0.0.1:9735"),
        ("udp localhost", "udp://localhost:9735"),
        ("public ipv4", "8.8.8.8:53"),
        ("public hostname", "example.com:443"),
        ("link local", "169.254.1.1:9735"),
        ("loop name", "loop:alice"),
        ("pipe name", "pipe:alice"),
        ("mailto", "mailto:a@b.com"),
        ("invalid", "nope"),
    ]
    connect = []
    for name, raw in connect_inputs:
        connect.append(
            {
                "name": name,
                "input": raw,
                "allowed": channel.is_connect_allowed(raw),
            }
        )

    def snapshot(a: channel.LoopChannel, b: channel.LoopChannel) -> Dict[str, Any]:
        return {
            "a_inbox": a.inbox(),
            "a_listen": a.listen_addr,
            "b_inbox": b.inbox(),
            "b_listen": b.listen_addr,
        }

    def run(name: str, note: str, ops) -> Dict[str, Any]:
        bus = channel.LoopBus()
        peers = {"a": channel.LoopChannel(bus), "b": channel.LoopChannel(bus)}
        steps = []
        for op in ops:
            who = op.get("who")
            actor = peers[who] if who else None
            kind = op["op"]
            if kind == "listen":
                ok = actor.listen(op["addr"])
                step = {"op": kind, "who": who, "addr": op["addr"], "ok": ok}
            elif kind == "dial":
                ok = actor.dial(op["addr"])
                step = {"op": kind, "who": who, "addr": op["addr"], "ok": ok}
            elif kind == "send":
                ok = actor.send(op["addr"], op["data"])
                step = {
                    "op": kind,
                    "who": who,
                    "addr": op["addr"],
                    "data": op["data"],
                    "ok": ok,
                }
            elif kind == "recv":
                returned = actor.recv()
                step = {"op": kind, "who": who, "returned": returned}
            elif kind == "close":
                actor.close()
                step = {"op": kind, "who": who}
            else:
                raise ValueError(kind)
            step.update(snapshot(peers["a"], peers["b"]))
            steps.append(step)
        return {"name": name, "note": note, "steps": steps}

    payload = "ab"
    oversize = "00" * (channel.MAX_LOOP_BYTES + 1)
    sequence = [
        run(
            "two peers exchange",
            "send does not require dial; recv drains FIFO",
            [
                {"op": "listen", "who": "a", "addr": "loop:alice"},
                {"op": "listen", "who": "b", "addr": "loop:bob"},
                {"op": "dial", "who": "a", "addr": "loop:bob"},
                {"op": "send", "who": "a", "addr": "loop:bob", "data": payload},
                {"op": "send", "who": "a", "addr": "loop:bob", "data": "cd"},
                {"op": "recv", "who": "b"},
                {"op": "recv", "who": "b"},
            ],
        ),
        run(
            "unbound and closed",
            "send fails when dest is not listening",
            [
                {"op": "listen", "who": "a", "addr": "loop:alice"},
                {"op": "send", "who": "a", "addr": "loop:bob", "data": payload},
                {"op": "listen", "who": "b", "addr": "loop:bob"},
                {"op": "send", "who": "a", "addr": "loop:bob", "data": payload},
                {"op": "close", "who": "b"},
                {"op": "send", "who": "a", "addr": "loop:bob", "data": payload},
                {"op": "dial", "who": "a", "addr": "loop:bob"},
            ],
        ),
        run(
            "rejects",
            "double listen, bad scheme, bad hex, oversize",
            [
                {"op": "listen", "who": "a", "addr": "loop:alice"},
                {"op": "listen", "who": "a", "addr": "loop:carol"},
                {"op": "listen", "who": "b", "addr": "loop:alice"},
                {"op": "listen", "who": "b", "addr": "tcp://127.0.0.1:1"},
                {"op": "send", "who": "a", "addr": "loop:alice", "data": "AB"},
                {"op": "send", "who": "a", "addr": "loop:alice", "data": "a"},
                {"op": "send", "who": "a", "addr": "loop:alice", "data": oversize},
                {"op": "send", "who": "b", "addr": "loop:alice", "data": payload},
            ],
        ),
    ]
    return {
        **header(
            "wire.channel",
            "SPEC/features/wire-channel.md",
            "Address URIs and an in-process loop channel.",
        ),
        "max_loop_bytes": channel.MAX_LOOP_BYTES,
        "parse": parse,
        "connect": connect,
        "sequence": sequence,
    }


def adapter_vectors() -> Dict[str, Any]:
    peer_a = "ab" * 32
    peer_b = "cd" * 32
    schemes = [
        ("udp", adapters.udp_bus, "udp://127.0.0.1:1", "udp://127.0.0.1:2"),
        ("mailto", adapters.mail_bus, "mailto:a@example.com", "mailto:b@example.com"),
        ("webrtc", adapters.webrtc_bus, f"webrtc:{peer_a}", f"webrtc:{peer_b}"),
        ("forum", adapters.forum_bus, "forum:disc:t1", "forum:disc:t2"),
        ("pipe", adapters.pipe_bus, "pipe:alice", "pipe:bob"),
    ]

    def snapshot(a: adapters.AdapterChannel, b: adapters.AdapterChannel) -> Dict[str, Any]:
        return {
            "a_inbox": a.inbox(),
            "a_listen": a.listen_addr,
            "b_inbox": b.inbox(),
            "b_listen": b.listen_addr,
        }

    def run(name: str, scheme: str, bus: adapters.AdapterBus, ops) -> Dict[str, Any]:
        peers = {
            "a": adapters.AdapterChannel(bus),
            "b": adapters.AdapterChannel(bus),
        }
        steps = []
        for op in ops:
            who = op["who"]
            actor = peers[who]
            kind = op["op"]
            if kind == "listen":
                ok = actor.listen(op["addr"])
                step: Dict[str, Any] = {"op": kind, "who": who, "addr": op["addr"], "ok": ok}
            elif kind == "dial":
                ok = actor.dial(op["addr"])
                step = {"op": kind, "who": who, "addr": op["addr"], "ok": ok}
            elif kind == "send":
                ok = actor.send(op["addr"], op["data"])
                step = {
                    "op": kind,
                    "who": who,
                    "addr": op["addr"],
                    "data": op["data"],
                    "ok": ok,
                }
            elif kind == "recv":
                step = {"op": kind, "who": who, "returned": actor.recv()}
            elif kind == "close":
                actor.close()
                step = {"op": kind, "who": who}
            else:
                raise ValueError(kind)
            step.update(snapshot(peers["a"], peers["b"]))
            steps.append(step)
        return {"name": name, "scheme": scheme, "steps": steps}

    payload = "ab"
    sequence = []
    for scheme, factory, addr_a, addr_b in schemes:
        sequence.append(
            run(
                f"{scheme} exchange",
                scheme,
                factory(),
                [
                    {"op": "listen", "who": "a", "addr": addr_a},
                    {"op": "listen", "who": "b", "addr": addr_b},
                    {"op": "dial", "who": "a", "addr": addr_b},
                    {"op": "send", "who": "a", "addr": addr_b, "data": payload},
                    {"op": "recv", "who": "b"},
                    {"op": "close", "who": "b"},
                    {"op": "send", "who": "a", "addr": addr_b, "data": payload},
                ],
            )
        )
    sequence.append(
        run(
            "mailto rejects",
            "mailto",
            adapters.mail_bus(),
            [
                {"op": "listen", "who": "a", "addr": "mailto:a@example.com"},
                {"op": "listen", "who": "a", "addr": "mailto:c@example.com"},
                {"op": "listen", "who": "b", "addr": "udp://127.0.0.1:9"},
                {"op": "send", "who": "a", "addr": "mailto:a@example.com", "data": "AB"},
                {"op": "send", "who": "a", "addr": "mailto:a@example.com", "data": "a"},
            ],
        )
    )
    return {
        **header(
            "channel.udp",
            "SPEC/features/channel-adapters.md",
            "UDP, mailto, webrtc, forum, and pipe adapters. Hello listen is unchanged.",
        ),
        "sequence": sequence,
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


def app_pubsub_vectors() -> Dict[str, Any]:
    def sub(room: str, author: str) -> Dict[str, Any]:
        return {"app": "pubsub", "author": author, "op": "subscribe", "room": room}

    def unsub(room: str, author: str) -> Dict[str, Any]:
        return {"app": "pubsub", "author": author, "op": "unsubscribe", "room": room}

    def pub(room: str, author: str, text: str, seq: int) -> Dict[str, Any]:
        return {
            "app": "pubsub",
            "author": author,
            "op": "publish",
            "room": room,
            "seq": seq,
            "text": text,
        }

    room_cap = [sub(f"room{i}", "alice") for i in range(MAX_ROOMS)]
    room_cap.append(sub(f"room{MAX_ROOMS}", "alice"))
    member_cap = [sub("general", f"m{i:02d}") for i in range(MAX_MEMBERS)]
    member_cap.append(sub("general", f"m{MAX_MEMBERS:02d}"))
    post_cap = [sub("general", "alice")]
    post_cap.extend(pub("general", "alice", f"n{i}", i) for i in range(MAX_POSTS))
    post_cap.append(pub("general", "alice", "overflow", MAX_POSTS))
    replay = [
        _replay_object(
            "join and speak",
            PubSub,
            [sub("general", "alice"), pub("general", "alice", "hello", 0)],
        ),
        _replay_object(
            "two chat rooms",
            PubSub,
            [
                sub("general", "alice"),
                sub("trading", "alice"),
                sub("general", "bob"),
                pub("general", "alice", "hello", 0),
                pub("trading", "alice", "bid", 0),
                pub("trading", "bob", "no", 0),
                pub("general", "bob", "hi", 0),
            ],
        ),
        _replay_object(
            "log order ignores arrival",
            PubSub,
            [
                sub("general", "alice"),
                sub("general", "bob"),
                pub("general", "bob", "from bob", 0),
                pub("general", "alice", "from alice", 0),
            ],
        ),
        _replay_object(
            "same text new seq",
            PubSub,
            [
                sub("general", "alice"),
                pub("general", "alice", "ok", 0),
                pub("general", "alice", "ok", 1),
            ],
        ),
        _replay_object(
            "duplicate seq rejected",
            PubSub,
            [
                sub("general", "alice"),
                pub("general", "alice", "one", 0),
                pub("general", "alice", "two", 0),
            ],
        ),
        _replay_object(
            "outsider cannot publish",
            PubSub,
            [sub("general", "alice"), pub("general", "bob", "hi", 0)],
        ),
        _replay_object(
            "leave keeps the log",
            PubSub,
            [
                sub("general", "alice"),
                pub("general", "alice", "hello", 0),
                unsub("general", "alice"),
                pub("general", "alice", "again", 1),
            ],
        ),
        _replay_object(
            "empty room disappears",
            PubSub,
            [sub("general", "alice"), unsub("general", "alice")],
        ),
        _replay_object(
            "resubscribe and speak",
            PubSub,
            [
                sub("general", "alice"),
                unsub("general", "alice"),
                sub("general", "alice"),
                pub("general", "alice", "back", 0),
            ],
        ),
        _replay_object(
            "idempotent subscribe",
            PubSub,
            [sub("general", "alice"), sub("general", "alice")],
        ),
        _replay_object(
            "unknown op rejected",
            PubSub,
            [{"app": "pubsub", "author": "alice", "op": "vote", "room": "general"}],
        ),
        _replay_object(
            "empty text rejected",
            PubSub,
            [sub("general", "alice"), pub("general", "alice", "", 0)],
        ),
        _replay_object(
            "text limits",
            PubSub,
            [
                sub("general", "alice"),
                pub("general", "alice", "a" * MAX_TEXT, 0),
                pub("general", "alice", "a" * (MAX_TEXT + 1), 1),
            ],
        ),
        _replay_object(
            "emoji text",
            PubSub,
            [sub("general", "alice"), pub("general", "alice", "hello 😀", 0)],
        ),
        _replay_object(
            "bad names rejected",
            PubSub,
            [
                sub("general chat", "alice"),
                sub("é", "alice"),
                sub("r" * 65, "alice"),
                sub("r" * 64, "alice"),
            ],
        ),
        _replay_object(
            "boolean seq rejected",
            PubSub,
            [sub("general", "alice"), {**pub("general", "alice", "x", 0), "seq": True}],
        ),
        _replay_object("room cap", PubSub, room_cap),
        _replay_object("member cap", PubSub, member_cap),
        _replay_object("post cap", PubSub, post_cap),
        _replay_object(
            "extra keys ignored",
            PubSub,
            [{**sub("general", "alice"), "note": "ignored"}],
        ),
    ]
    return {
        **header(
            "app.pubsub",
            "SPEC/features/app-pubsub.md",
            "Topic publish-subscribe: rooms, membership, deterministic log.",
        ),
        "replay": replay,
    }


def _replay_stream(name: str, messages: List[Any]) -> Dict[str, Any]:
    obj = Stream()
    steps = []
    for message in messages:
        accepted = obj.is_valid(message)
        if accepted:
            obj.add_message(message)
        state = obj.state()
        step: Dict[str, Any] = {
            "message_json": canonical_json(message),
            "accepted": accepted,
            **state,
        }
        reads = _stream_reads(obj, state)
        if reads is not None:
            step["reads"] = reads
        steps.append(step)
    return {"name": name, "steps": steps}


def _stream_reads(obj: Stream, state: Dict[str, Any]) -> Any:
    count = sum(
        len(part["events"]) for item in state["streams"] for part in item["partitions"]
    )
    if count > 8:
        return None
    names = [item["name"] for item in state["streams"]] or ["missing"]
    probes = []
    for stream_name in names:
        events = obj.read(stream_name, 0, None, 4)
        probes.append(
            {
                "after": None,
                "events": events,
                "limit": 4,
                "partition": 0,
                "stream": stream_name,
            }
        )
        if events:
            after = {"producer": events[0]["producer"], "seq": events[0]["seq"]}
            probes.append(
                {
                    "after": after,
                    "events": obj.read(stream_name, 0, after, 4),
                    "limit": 4,
                    "partition": 0,
                    "stream": stream_name,
                }
            )
    first = names[0]
    bad = {"producer": "alice", "seq": True}
    probes.append(
        {
            "after": None,
            "events": obj.read("missing", 0, None, 4),
            "limit": 4,
            "partition": 0,
            "stream": "missing",
        }
    )
    probes.append(
        {
            "after": None,
            "events": obj.read(first, 0, None, 0),
            "limit": 0,
            "partition": 0,
            "stream": first,
        }
    )
    probes.append(
        {
            "after": bad,
            "events": obj.read(first, 0, bad, 4),
            "limit": 4,
            "partition": 0,
            "stream": first,
        }
    )
    return probes


def app_stream_vectors() -> Dict[str, Any]:
    def open_(stream: str, producer: str) -> Dict[str, Any]:
        return {"app": "stream", "op": "open", "producer": producer, "stream": stream}

    def produce(stream: str, producer: str, seq: int, payload: str) -> Dict[str, Any]:
        return {
            "app": "stream",
            "op": "produce",
            "payload": payload,
            "producer": producer,
            "seq": seq,
            "stream": stream,
        }

    def commit(stream: str, group: str, producer: str, seq: int) -> Dict[str, Any]:
        return {
            "app": "stream",
            "group": group,
            "op": "commit",
            "producer": producer,
            "seq": seq,
            "stream": stream,
        }

    def record(producer: str, seq: int, payload: str) -> Dict[str, Any]:
        return {"payload": payload, "producer": producer, "seq": seq}

    def append(stream: str, records: List[Dict[str, Any]], partition: int = 0) -> Dict[str, Any]:
        return {
            "app": "stream",
            "op": "append",
            "partition": partition,
            "records": records,
            "stream": stream,
        }

    def join(stream: str, broker: str) -> Dict[str, Any]:
        return {"app": "stream", "broker": broker, "op": "join", "stream": stream}

    def fail(stream: str, broker: str) -> Dict[str, Any]:
        return {"app": "stream", "broker": broker, "op": "fail", "stream": stream}

    def retain(stream: str, keep: int) -> Dict[str, Any]:
        return {"app": "stream", "keep": keep, "op": "retain", "stream": stream}

    stream_cap = [open_(f"s{i:02d}", "alice") for i in range(MAX_STREAMS)]
    stream_cap.append(open_(f"s{MAX_STREAMS:02d}", "alice"))
    producer_cap = [open_("orders", f"p{i:02d}") for i in range(MAX_PRODUCERS)]
    producer_cap.append(open_("orders", f"p{MAX_PRODUCERS:02d}"))
    event_cap = [open_("orders", "alice")]
    event_cap.extend(produce("orders", "alice", i, "x") for i in range(MAX_EVENTS))
    event_cap.append(produce("orders", "alice", MAX_EVENTS, "x"))
    event_cap.append(produce("orders", "alice", 0, "x"))
    group_cap = [open_("orders", "alice"), produce("orders", "alice", 0, "x")]
    group_cap.extend(commit("orders", f"g{i:02d}", "alice", 0) for i in range(MAX_GROUPS))
    group_cap.append(commit("orders", f"g{MAX_GROUPS:02d}", "alice", 0))
    partition_cap = [{**open_("orders", "alice"), "partition": i} for i in range(MAX_PARTITIONS)]
    partition_cap.append({**open_("orders", "alice"), "partition": MAX_PARTITIONS})
    broker_cap = [open_("orders", "alice")]
    broker_cap.extend(join("orders", f"n{i}") for i in range(MAX_BROKERS))
    broker_cap.append(join("orders", f"n{MAX_BROKERS}"))
    replay = [
        _replay_stream(
            "open produce commit",
            [
                open_("orders", "alice"),
                produce("orders", "alice", 0, "created"),
                commit("orders", "workers", "alice", 0),
            ],
        ),
        _replay_stream(
            "two streams",
            [
                open_("orders", "alice"),
                open_("trades", "bob"),
                produce("orders", "alice", 0, "o"),
                produce("trades", "bob", 0, "t"),
            ],
        ),
        _replay_stream(
            "log order ignores arrival",
            [
                open_("orders", "alice"),
                open_("orders", "bob"),
                produce("orders", "bob", 0, "from bob"),
                produce("orders", "alice", 0, "from alice"),
            ],
        ),
        _replay_stream(
            "gap then fill",
            [
                open_("orders", "alice"),
                open_("orders", "bob"),
                produce("orders", "alice", 0, "a0"),
                produce("orders", "alice", 2, "a2"),
                produce("orders", "bob", 0, "b0"),
                commit("orders", "workers", "alice", 2),
                commit("orders", "workers", "bob", 0),
                commit("orders", "workers", "alice", 0),
                produce("orders", "alice", 1, "a1"),
                commit("orders", "workers", "alice", 2),
                commit("orders", "workers", "alice", 0),
                commit("orders", "auditors", "alice", 1),
            ],
        ),
        _replay_stream(
            "identical produce is a no-op",
            [
                open_("orders", "alice"),
                produce("orders", "alice", 0, "one"),
                produce("orders", "alice", 0, "one"),
            ],
        ),
        _replay_stream(
            "conflicting payload rejected",
            [
                open_("orders", "alice"),
                produce("orders", "alice", 0, "one"),
                produce("orders", "alice", 0, "two"),
            ],
        ),
        _replay_stream("produce before open rejected", [produce("orders", "alice", 0, "x")]),
        _replay_stream("idempotent open", [open_("orders", "alice"), open_("orders", "alice")]),
        _replay_stream(
            "unknown op rejected",
            [{"app": "stream", "op": "vote", "producer": "alice", "stream": "orders"}],
        ),
        _replay_stream(
            "empty payload rejected",
            [open_("orders", "alice"), produce("orders", "alice", 0, "")],
        ),
        _replay_stream(
            "payload limits",
            [
                open_("orders", "alice"),
                produce("orders", "alice", 0, "a" * MAX_PAYLOAD),
                produce("orders", "alice", 1, "a" * (MAX_PAYLOAD + 1)),
            ],
        ),
        _replay_stream(
            "emoji payload",
            [open_("orders", "alice"), produce("orders", "alice", 0, "hello 😀")],
        ),
        _replay_stream(
            "bad names rejected",
            [
                open_("orders", "bad name"),
                open_("é", "alice"),
                open_("s" * 65, "alice"),
                open_("s" * 64, "alice"),
            ],
        ),
        _replay_stream(
            "boolean seq rejected",
            [open_("orders", "alice"), {**produce("orders", "alice", 0, "x"), "seq": True}],
        ),
        _replay_stream(
            "sparse high seq commit rejected",
            [
                open_("orders", "alice"),
                produce("orders", "alice", MAX_SAFE_INT, "z"),
                commit("orders", "workers", "alice", MAX_SAFE_INT),
            ],
        ),
        _replay_stream("extra keys ignored", [{**open_("orders", "alice"), "note": "ignored"}]),
        _replay_stream("stream cap", stream_cap),
        _replay_stream("producer cap", producer_cap),
        _replay_stream("event cap", event_cap),
        _replay_stream("group cap", group_cap),
        _replay_stream("partition cap", partition_cap),
        _replay_stream("broker cap", broker_cap),
        _replay_stream(
            "batch append",
            [
                open_("orders", "alice"),
                append(
                    "orders",
                    [record("alice", 0, "a"), record("alice", 1, "b"), record("alice", 2, "c")],
                ),
            ],
        ),
        _replay_stream(
            "batch is all or nothing",
            [
                open_("orders", "alice"),
                produce("orders", "alice", 0, "a"),
                append("orders", [record("alice", 1, "b"), record("alice", 0, "other")]),
            ],
        ),
        _replay_stream(
            "batch cap",
            [
                open_("orders", "alice"),
                append("orders", [record("alice", i, "x") for i in range(MAX_BATCH + 1)]),
            ],
        ),
        _replay_stream(
            "new partition leaves the first",
            [
                {**open_("orders", "alice"), "partition": 0},
                produce("orders", "alice", 0, "p0"),
                {**open_("orders", "alice"), "partition": 1},
                {**produce("orders", "alice", 0, "p1"), "partition": 1},
            ],
        ),
        _replay_stream(
            "replica survives one failure",
            [
                join("orders", "n1"),
                join("orders", "n2"),
                open_("orders", "alice"),
                produce("orders", "alice", 0, "kept"),
                fail("orders", "n1"),
                produce("orders", "alice", 1, "still"),
                fail("orders", "n2"),
                produce("orders", "alice", 2, "paused"),
                join("orders", "n1"),
                produce("orders", "alice", 2, "resumed"),
            ],
        ),
        _replay_stream(
            "retention then replay",
            [
                open_("orders", "alice"),
                produce("orders", "alice", 0, "a"),
                produce("orders", "alice", 1, "b"),
                produce("orders", "alice", 2, "c"),
                retain("orders", 2),
                produce("orders", "alice", 0, "a"),
                commit("orders", "late", "alice", 2),
                commit("orders", "late", "alice", 1),
            ],
        ),
        _replay_stream(
            "pipeline stages are separate streams",
            [
                open_("orders", "alice"),
                produce("orders", "alice", 0, "created"),
                open_("billing", "worker"),
                produce("billing", "worker", 0, "invoice"),
            ],
        ),
        _replay_stream(
            "boolean partition rejected",
            [open_("orders", "alice"), {**produce("orders", "alice", 0, "x"), "partition": True}],
        ),
    ]
    return {
        **header(
            "app.stream",
            "SPEC/features/app-stream.md",
            "Append-only event log: batches, partitions, replicas, retention, replay.",
        ),
        "replay": replay,
    }


def protocol_crdt_kv_vectors() -> Dict[str, Any]:
    def set_(key: str, writer: str, ts: int, value: str) -> Dict[str, Any]:
        return {
            "app": "crdt",
            "key": key,
            "op": "set",
            "ts": ts,
            "value": value,
            "writer": writer,
        }

    def delete(key: str, writer: str, ts: int) -> Dict[str, Any]:
        return {"app": "crdt", "key": key, "op": "del", "ts": ts, "writer": writer}

    cap = [set_(f"k{i:02d}", "alice", 1, "v") for i in range(MAX_KEYS)]
    cap.append(set_(f"k{MAX_KEYS:02d}", "alice", 1, "v"))
    replay = [
        _replay_object("set then overwrite", CrdtKv, [set_("x", "alice", 1, "one"), set_("x", "alice", 2, "two")]),
        _replay_object(
            "concurrent tie lowest writer",
            CrdtKv,
            [set_("x", "bob", 5, "from-bob"), set_("x", "alice", 5, "from-alice")],
        ),
        _replay_object(
            "tombstone then revive",
            CrdtKv,
            [set_("x", "alice", 1, "hello"), delete("x", "alice", 2), set_("x", "bob", 3, "back")],
        ),
        _replay_object(
            "idempotent replay",
            CrdtKv,
            [set_("x", "alice", 1, "hello"), set_("x", "alice", 1, "hello")],
        ),
        _replay_object(
            "stale write and conflict rejected",
            CrdtKv,
            [
                set_("x", "alice", 2, "new"),
                set_("x", "alice", 1, "old"),
                set_("x", "alice", 2, "other"),
            ],
        ),
        _replay_object("key cap", CrdtKv, cap),
    ]
    return {
        **header(
            "protocol.crdt-kv",
            "SPEC/features/protocol-crdt-kv.md",
            "LWW key-value: higher ts wins, equal ts lowest writer, tombstones.",
        ),
        "max_keys": MAX_KEYS,
        "replay": replay,
    }


def paths_vectors() -> Dict[str, Any]:
    types = [
        "ctl.hello",
        "ctl.digest",
        "ctl.messages.request",
        "link.pubsub.typing",
        "link.bittorrent.request",
        "app.pubsub",
        "app.bittorrent",
        "link",
        "ctl",
        "applink.test",
    ]
    classify = []
    for type_name in types:
        env = Envelope.build(type_name, {"n": 1}, ts=TS)
        dedup = Deduplicator()
        first = dedup.should_process(env)
        repeat = dedup.should_process(env)
        classify.append(
            {
                "name": type_name,
                "type": type_name,
                "ts": TS,
                "path": env.path(),
                "relay": dedup.should_relay(env),
                "first_process": first,
                "repeat_process": repeat,
                "seen_size": len(dedup.seen),
            }
        )
    return {
        **header(
            "wire.paths",
            "SPEC/features/wire-paths.md",
            "Gossip is relayed. ctl.* and link.* stay on the delivering peer.",
        ),
        "now_ms": NOW,
        "classify": classify,
    }


def channel_peer_vectors() -> Dict[str, Any]:
    from chaincraft.peer import (
        DEFAULT_PEER_ORIGIN,
        EnvelopeRelay,
        parse_peer_id_body,
        peer_options,
    )

    ids = []
    for name, raw in (
        ("empty", ""),
        ("uuid", "283e9542-cc0a-4301-8c37-70cd162fa2f8"),
        ("hex64", "ab" * 32),
        ("short", "abcd"),
        ("trim", "  abcd\n"),
        ("upper", "Abcd"),
        ("underscore", "peer_1"),
        ("space", "bad id"),
        ("dot", "ab.cd"),
        ("too long", "a" * 65),
        ("slash", "ab/cd"),
    ):
        ids.append({"name": name, "input": raw, "id": parse_peer_id_body(raw)})

    relay = EnvelopeRelay()
    steps: List[Dict[str, Any]] = []
    peer_addr = "webrtc:283e9542-cc0a-4301-8c37-70cd162fa2f8"
    pipe_addr = "pipe:alice"
    mail_addr = "mailto:bob@example.com"

    def join(addr: str) -> None:
        steps.append({"op": "join", "addr": addr, "ok": relay.join(addr)})

    def publish(src: str, data: Dict[str, Any]) -> None:
        steps.append(
            {
                "op": "publish",
                "src": src,
                "type": "app.hello",
                "data": json.dumps(data, separators=(",", ":"), ensure_ascii=False),
                "id": relay.publish(src, "app.hello", data),
            }
        )

    def take(addr: str) -> None:
        steps.append({"op": "take", "addr": addr, "inbox": relay.take(addr)})

    join(peer_addr)
    join(pipe_addr)
    join(mail_addr)
    join(peer_addr)
    join("tcp://127.0.0.1:9735")
    join("webrtc:bad id")
    publish(peer_addr, {"message": "hi"})
    take(pipe_addr)
    take(mail_addr)
    take(peer_addr)
    publish(peer_addr, {"message": "hi"})
    take(pipe_addr)
    publish("pipe:nobody", {"message": "no"})
    publish(pipe_addr, {"message": "ho"})
    take(peer_addr)
    take(mail_addr)
    take(pipe_addr)
    return {
        **header(
            "channel.peer",
            "SPEC/features/channel-peer.md",
            "PeerJS ids, default broker options, and one cross-scheme relay.",
        ),
        "origin": DEFAULT_PEER_ORIGIN,
        "options": peer_options(),
        "ids": ids,
        "steps": steps,
    }


def channel_hybrid_vectors() -> Dict[str, Any]:
    from chaincraft.envelope import Envelope
    from chaincraft.hybrid import LinkMesh, hello_caps

    def sized(n: int) -> Dict[str, str]:
        return {"message": "x" * n}

    wide = sized(1)
    while len(Envelope.build("app.hello", wide, ts=0).to_bytes()) <= 4096:
        wide = sized(len(wide["message"]) + 200)
    assert len(Envelope.build("app.hello", wide, ts=0).to_bytes()) <= 65507

    mesh = LinkMesh()
    steps: List[Dict[str, Any]] = []
    webrtc = "webrtc:283e9542-cc0a-4301-8c37-70cd162fa2f8"
    pipe = "pipe:alice"
    mail = "mailto:bob@example.com"

    def join(addr: str) -> None:
        steps.append({"op": "join", "addr": addr, "ok": mesh.join(addr)})

    def gossip(src: str, data: Dict[str, Any]) -> None:
        steps.append(
            {
                "op": "gossip",
                "src": src,
                "type": "app.hello",
                "data": json.dumps(data, separators=(",", ":"), ensure_ascii=False),
                "id": mesh.gossip(src, "app.hello", data),
            }
        )

    def direct(src: str, dst: str, data: Dict[str, Any]) -> None:
        steps.append(
            {
                "op": "direct",
                "src": src,
                "dst": dst,
                "type": "link.note",
                "data": json.dumps(data, separators=(",", ":"), ensure_ascii=False),
                "id": mesh.direct(src, dst, "link.note", data),
            }
        )

    def take(addr: str) -> None:
        steps.append({"op": "take", "addr": addr, "inbox": mesh.take(addr)})

    join(webrtc)
    join(pipe)
    join(mail)
    join(webrtc)
    join("webrtc:bad id")
    gossip(webrtc, {"message": "hi"})
    take(pipe)
    take(mail)
    take(webrtc)
    gossip(webrtc, {"message": "hi"})
    take(pipe)
    gossip(webrtc, wide)
    take(pipe)
    take(mail)
    direct(pipe, mail, {"note": "one"})
    take(mail)
    take(webrtc)
    return {
        **header(
            "channel.hybrid",
            "SPEC/features/channel-hybrid.md",
            "One mesh relays gossip across schemes and drops an oversized hop.",
        ),
        "caps_tcp": hello_caps(False),
        "caps_udp": hello_caps(True),
        "steps": steps,
    }


def _chain_transfer_step_state(chain: Any) -> Dict[str, Any]:
    st = chain.state()
    return {
        "balances": st["balances"],
        "canonical": st["canonical"],
        "height": st["height"],
        "nonces": st["nonces"],
        "tip": st["tip"],
    }


def _chain_transfer_replay_case(
    name: str,
    consensus: str,
    options: Dict[str, Any],
    reward: int,
    genesis: Dict[str, int],
    message_json: str,
) -> Dict[str, Any]:
    from chaincraft.chain import TransferChain
    from chaincraft.chain_driver import make_driver

    driver = make_driver(consensus, **options)
    chain = TransferChain(genesis, reward=reward, driver=driver)
    steps: List[Dict[str, Any]] = []
    message = parse_json(message_json)
    accepted = chain.submit(message)
    steps.append(
        {
            "op": "submit",
            "accepted": accepted,
            "message_json": message_json,
            **_chain_transfer_step_state(chain),
        }
    )
    for time, producer in ((1, "alice"), (2, "alice")):
        block = chain.produce(time, producer)
        steps.append(
            {
                "op": "produce",
                "accepted": block is not None,
                "producer": producer,
                "time": time,
                **_chain_transfer_step_state(chain),
            }
        )
    return {
        "consensus": consensus,
        "name": name,
        "options": options,
        "reward": reward,
        "steps": steps,
    }


def chain_transfer_vectors() -> Dict[str, Any]:
    from chaincraft.chain import sign_transfer

    sender_pk = crypto.public_key(crypto.SCHNORR, SECKEY_B).hex()
    genesis = {sender_pk: 1000, "bob": 50}
    tx = sign_transfer(
        {
            "amount": 10,
            "fee": 2,
            "nonce": 0,
            "recipient": "bob",
            "sender": sender_pk,
        },
        SECKEY_B,
        AUX,
    )
    message_json = canonical_json(tx)
    return {
        **header(
            "chain.transfer",
            "SPEC/features/chain-transfer.md",
            "Account transfer chain with consensus drivers.",
        ),
        "genesis": genesis,
        "replay": [
            _chain_transfer_replay_case(
                "poa two blocks with transfer",
                "poa",
                {"authorities": ["alice"]},
                1,
                genesis,
                message_json,
            ),
            _chain_transfer_replay_case(
                "pow two blocks with transfer",
                "pow",
                {},
                1,
                genesis,
                message_json,
            ),
        ],
        "sender_aux": AUX.hex(),
        "sender_pk": sender_pk,
        "sender_sk": SECKEY_B.hex(),
    }


def node_preset_vectors() -> Dict[str, Any]:
    from chaincraft.chain import TransferChain
    from chaincraft.chain_driver import make_driver
    from chaincraft import preset

    valid_config = {
        "authorities": ["alice"],
        "consensus": "poa",
        "genesis": {"alice": 100},
        "listen": "127.0.0.1:0",
        "peers": [],
        "protocol": "transfer",
        "reward": 0,
        "udp": False,
    }
    handle = preset.start(dict(valid_config))
    driver = make_driver("poa", authorities=["alice"])
    chain = TransferChain(valid_config["genesis"], reward=0, driver=driver)
    block = chain.produce(1, "alice")
    handle["close"]()
    return {
        **header(
            "node.preset",
            "SPEC/features/node-preset.md",
            "Preset transfer node and config validation.",
        ),
        "valid_config": valid_config,
        "valid_listen_prefix": "127.0.0.1:",
        "hand_built_block": block,
        "rejections": [
            {"config": {"protocol": "nope"}, "error": "invalid protocol"},
            {
                "config": {
                    "consensus": "poa",
                    "extra": 1,
                    "genesis": {"alice": 100},
                    "protocol": "transfer",
                },
                "error": "unknown config key",
            },
        ],
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
    write("wire-paths.json", paths_vectors())
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
    write("discovery-ban.json", discovery_ban_vectors())
    print("\nLevel 2 — consensus")
    write("consensus-poa.json", consensus_poa_vectors())
    write("consensus-poet.json", consensus_poet_vectors())
    write("consensus-beacon.json", consensus_beacon_vectors())
    write("consensus-pox.json", consensus_pox_vectors())
    write("consensus-ouroboros.json", consensus_ouroboros_vectors())
    write("consensus-pow.json", consensus_pow_vectors())
    write("consensus-pos.json", consensus_pos_vectors())
    write("consensus-pbft.json", consensus_pbft_vectors())
    write("consensus-avalanche.json", consensus_avalanche_vectors())
    print("\nLevel 2 — ledgers")
    write("ledger-balance.json", ledger_balance_vectors())
    write("ledger-utxo.json", ledger_utxo_vectors())
    print("\nLevel 2 — mempool and fees")
    write("mempool-basic.json", mempool_basic_vectors())
    write("fees-policy.json", fees_policy_vectors())
    print("\nLevel 2 — storage and CLI")
    write("storage-persistent.json", storage_persistent_vectors())
    write("storage-index.json", storage_index_vectors())
    write("cli-node.json", cli_node_vectors())
    print("\nLevel 2 — BitTorrent swarm")
    write("bittorrent-swarm.json", bittorrent_swarm_vectors())
    print("\nLevel 2 — NAT traversal")
    write("discovery-nat.json", discovery_nat_vectors())
    print("\nLevel 2 — channel")
    write("wire-channel.json", wire_channel_vectors())
    write("channel-adapters.json", adapter_vectors())
    write("channel-peer.json", channel_peer_vectors())
    write("channel-hybrid.json", channel_hybrid_vectors())
    print("\nLevel 2 — publish-subscribe")
    write("app-pubsub.json", app_pubsub_vectors())
    print("\nLevel 2 — event stream")
    write("app-stream.json", app_stream_vectors())
    print("\nLevel 2 — CRDT key-value")
    write("protocol-crdt-kv.json", protocol_crdt_kv_vectors())
    print("\nLevel 2 — transfer chain and preset")
    write("chain-transfer.json", chain_transfer_vectors())
    write("node-preset.json", node_preset_vectors())
    print(f"\nWritten to {VECTORS.relative_to(REPO)}")
    print("A diff here means the wire protocol changed. See AGENTS.md section 7.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
