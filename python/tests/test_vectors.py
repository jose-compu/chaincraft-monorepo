"""Conformance vectors — the shared cross-language contract.

Every implementation runs these same files. This module is the template the Rust
and TypeScript suites mirror.

A failure here is a wire protocol violation, not a local bug. Never edit a vector
to make a test pass; see AGENTS.md section 7.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conformance_objects import build_registry, snapshot

from chaincraft_core import control, crypto, framing
from chaincraft_core.canonical import CanonicalError, canonical_json, parse_json, payload_digest
from chaincraft_core.dedup import Deduplicator
from chaincraft_core.envelope import Envelope, ProtocolError
from chaincraft_core.framing import FrameReader, FramingError, encode_frame
from chaincraft_core.memento import StateMemento
from chaincraft_core.object import frontier_digest, merkle_digest, wins_replacement

VECTORS = Path(__file__).resolve().parent.parent.parent / "conformance" / "vectors"


def load(name: str) -> dict:
    path = VECTORS / name
    if not path.exists():
        pytest.skip(f"{name} not generated; run conformance/generate_vectors.py")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def cases(name: str, section: str):
    """Parametrize over a vector section, labelled by case name."""
    data = load(name)
    entries = data.get(section, [])
    return pytest.mark.parametrize(
        "case", entries, ids=[c.get("name", str(i)) for i, c in enumerate(entries)]
    )


# --- wire.canonical-json ----------------------------------------------------


@cases("canonical-json.json", "valid")
def test_canonical_valid(case):
    assert canonical_json(parse_json(case["input_json"])) == case["canonical"]


@cases("canonical-json.json", "invalid")
def test_canonical_invalid(case):
    with pytest.raises(CanonicalError):
        canonical_json(parse_json(case["input_json"]))


# --- wire.payload-digest ----------------------------------------------------


@cases("digest.json", "valid")
def test_digest(case):
    data = parse_json(case["data_json"])
    assert canonical_json(data) == case["canonical"]
    assert payload_digest(data) == case["digest"]


# --- wire.envelope ----------------------------------------------------------


@cases("envelope.json", "valid")
def test_envelope_valid(case):
    env = Envelope.build(case["type"], parse_json(case["data_json"]), ts=case["ts"])
    assert env.id == case["id"]
    assert env.to_json() == case["canonical"]
    assert Envelope.parse(case["canonical"], now_ms=load("envelope.json")["now_ms"]) == env


@cases("envelope.json", "invalid")
def test_envelope_invalid(case):
    with pytest.raises(ProtocolError):
        Envelope.parse(case["envelope_json"], now_ms=load("envelope.json")["now_ms"])


# --- wire.framing-tcp -------------------------------------------------------


@cases("framing.json", "valid")
def test_framing_encode(case):
    assert encode_frame(bytes.fromhex(case["body_hex"])).hex() == case["frame_hex"]


@cases("framing.json", "stream")
def test_framing_stream(case):
    reader = FrameReader()
    received = []
    for chunk in case["chunks_hex"]:
        received.extend(reader.feed(bytes.fromhex(chunk)))
    assert [f.hex() for f in received] == case["frames_hex"]


@cases("framing.json", "invalid")
def test_framing_invalid(case):
    with pytest.raises(FramingError):
        FrameReader().feed(bytes.fromhex(case["input_hex"]))


# --- wire.framing-udp -------------------------------------------------------


@cases("framing.json", "udp_valid")
def test_framing_udp_valid(case):
    body = bytes.fromhex(case["body_hex"])
    assert framing.encode_datagram(body) == body
    assert framing.decode_datagram(body) == body


@cases("framing.json", "udp_invalid")
def test_framing_udp_invalid(case):
    # Oversized cases carry a length rather than megabytes of embedded hex.
    if case["input_hex"] is None:
        data = b"x" * case["input_length"]
    else:
        data = bytes.fromhex(case["input_hex"])
    with pytest.raises(FramingError):
        framing.decode_datagram(data)
    with pytest.raises(FramingError):
        framing.encode_datagram(data)


# --- wire.control -----------------------------------------------------------

_BUILDERS = {
    "hello minimal": lambda ts: control.hello("py-chaincraft/1.0.0", ts=ts),
    "hello with listen and caps": lambda ts: control.hello(
        "py-chaincraft/1.0.0",
        caps=["udp", "gossip", "digest-sync"],
        listen="10.0.0.2:9735",
        ts=ts,
    ),
    "peers request": lambda ts: control.peers_request(ts=ts),
    "peers response": lambda ts: control.peers(
        ["10.0.0.2:9735", "10.0.0.3:9735"], ts=ts
    ),
    "digest request": lambda ts: control.digest_request("BalanceLedger", ts=ts),
    "digest response": lambda ts: control.digest(
        "BalanceLedger", "ab" * 32, ["cd" * 32], ts=ts
    ),
    "messages request": lambda ts: control.messages_request(
        "BalanceLedger", "ab" * 32, ts=ts
    ),
    "messages response": lambda ts: control.messages(
        "BalanceLedger", [Envelope.build("app.t", {"n": 1}, ts=ts)], ts=ts
    ),
}


@cases("control.json", "valid")
def test_control_valid(case):
    now = load("control.json")["now_ms"]
    parsed = Envelope.parse(case["canonical"], now_ms=now)
    assert parsed.type == case["type"]
    assert parsed.id == case["id"]

    builder = _BUILDERS.get(case["name"])
    assert builder is not None, f"no builder registered for {case['name']!r}"
    assert builder(parsed.ts).to_json() == case["canonical"]


@cases("control.json", "invalid")
def test_control_invalid(case):
    env = Envelope.parse(case["envelope_json"], now_ms=load("control.json")["now_ms"])
    with pytest.raises(ProtocolError):
        control.parse_hello(env)


# --- wire.sig-schnorr -------------------------------------------------------


@cases("signatures.json", "valid")
def test_signature_valid(case):
    seckey = bytes.fromhex(case["secret_key"])
    message = bytes.fromhex(case["message"])

    assert crypto.public_key(case["alg"], seckey).hex() == case["public_key"]

    produced = crypto._schnorr_sign(message, seckey, bytes.fromhex(case["aux"]))
    assert produced.hex() == case["signature"], "deterministic signing must match"

    assert crypto.verify(
        case["alg"], message, produced, bytes.fromhex(case["public_key"])
    )

    if "canonical" in case:
        env = Envelope.parse(case["canonical"], now_ms=10**13)
        assert env.verify()


@cases("signatures.json", "invalid")
def test_signature_invalid(case):
    """Verification returns False on bad input and never raises into receive."""
    result = crypto.verify(
        case["alg"],
        bytes.fromhex(case["message"]),
        bytes.fromhex(case["signature"]),
        bytes.fromhex(case["public_key"]),
    )
    assert result is False


# --- wire.dedup -------------------------------------------------------------


@cases("dedup.json", "sequence")
def test_dedup_sequence(case):
    """Replay a delivery sequence, checking the decision at every step.

    The eviction case only distinguishes FIFO-by-first-insertion from a policy
    that refreshes on re-see if each step is checked in order.
    """
    now = load("dedup.json")["now_ms"]
    dedup = Deduplicator(case["capacity"])
    for index, step in enumerate(case["steps"]):
        env = Envelope.parse(step["canonical"], now_ms=now)
        where = f"step {index} ({step['type']} {step['id'][:8]})"
        assert env.id == step["id"], where
        assert dedup.should_process(env) is step["should_process"], where
        assert dedup.should_relay(env) is step["should_relay"], where
        assert len(dedup.seen) == step["seen_size"], where


# --- object.memento, object.merkle-digest -----------------------------------


@cases("memento.json", "normalize")
def test_memento_normalize(case):
    memento = StateMemento.normalize(
        case["input"]["canonical_digest"], case["input"]["frontier_digests"]
    )
    assert memento.to_dict() == case["expected"]


@cases("memento.json", "reorg")
def test_memento_reorg(case):
    current = StateMemento.normalize(
        case["current"]["canonical_digest"], case["current"]["frontier_digests"]
    )
    previous = (
        StateMemento.normalize(
            case["previous"]["canonical_digest"], case["previous"]["frontier_digests"]
        )
        if case["previous"]
        else None
    )
    assert current.indicates_reorg_against(previous) is case["expected"]


@cases("memento.json", "merkle")
def test_merkle_digest(case):
    payload = parse_json(case["payload_json"])
    assert canonical_json(payload) == case["canonical"]
    assert merkle_digest(payload) == case["digest"]


@cases("memento.json", "frontier")
def test_frontier_digest(case):
    assert frontier_digest(case["heads"]) == case["digest"]


# --- object.pipeline, object.contract, object.tiebreak ----------------------


@cases("pipeline.json", "replay")
def test_pipeline_replay(case):
    """Replay a sequence through the section 8 registry, checking every step.

    Asserting after each message rather than only at the end is what catches a
    rejection that mutated state and was then masked by a later success.
    """
    assert load("pipeline.json")["registry"] == build_registry().names

    registry = build_registry()
    for index, step in enumerate(case["steps"]):
        result = registry.apply(parse_json(step["message_json"]))
        where = f"step {index} ({step['message_json']})"
        assert result.accepted is step["accepted"], where
        assert result.rejected_by == step["rejected_by"], where
        assert snapshot(registry) == {
            "counter": step["counter"],
            "mirror": step["mirror"],
        }, where


@cases("pipeline.json", "tiebreak")
def test_replacement_tiebreak(case):
    assert (
        wins_replacement(
            case["candidate"]["rank"],
            case["candidate"]["digest"],
            case["incumbent"]["rank"],
            case["incumbent"]["digest"],
        )
        is case["expected"]
    )


# --- Level 2 crypto ---------------------------------------------------------


@cases("ecdsa.json", "valid")
def test_ecdsa_valid(case):
    from chaincraft_core import ecdsa

    key = bytes.fromhex(case["secret_key"])
    message = bytes.fromhex(case["message_hex"])
    assert ecdsa.public_key(key).hex() == case["public_key"]
    assert ecdsa.sign(message, key).hex() == case["signature"]
    assert ecdsa.verify(message, bytes.fromhex(case["signature"]), bytes.fromhex(case["public_key"]))


@cases("ecdsa.json", "invalid")
def test_ecdsa_invalid(case):
    from chaincraft_core import ecdsa

    assert (
        ecdsa.verify(
            bytes.fromhex(case["message_hex"]),
            bytes.fromhex(case["signature"]),
            bytes.fromhex(case["public_key"]),
        )
        is False
    )


@cases("vdf.json", "valid")
def test_vdf_valid(case):
    from chaincraft_core import vdf

    proof = vdf.evaluate(bytes.fromhex(case["seed_hex"]), case["t"])
    assert vdf.proof_to_hex(proof) == case["proof"]
    assert vdf.verify(bytes.fromhex(case["seed_hex"]), case["t"], proof)


@cases("vdf.json", "invalid")
def test_vdf_invalid(case):
    from chaincraft_core import vdf

    assert (
        vdf.verify(
            bytes.fromhex(case["seed_hex"]),
            case["t"],
            vdf.hex_to_proof(case["proof"]),
        )
        is False
    )


@cases("vrf.json", "valid")
def test_vrf_valid(case):
    from chaincraft_core import vrf

    proof, output, pk = vrf.evaluate(bytes.fromhex(case["message_hex"]), bytes.fromhex(case["secret_key"]))
    assert pk.hex() == case["public_key"]
    assert proof.hex() == case["proof"]
    assert output.hex() == case["output"]
    assert vrf.verify(bytes.fromhex(case["message_hex"]), proof, pk, output)


@cases("vrf.json", "invalid")
def test_vrf_invalid(case):
    from chaincraft_core import vrf

    assert (
        vrf.verify(
            bytes.fromhex(case["message_hex"]),
            bytes.fromhex(case["proof"]),
            bytes.fromhex(case["public_key"]),
            bytes.fromhex(case["output"]),
        )
        is False
    )


# --- Level 2 discovery ------------------------------------------------------


@cases("discovery-peer.json", "valid")
def test_discovery_peer_valid(case):
    from chaincraft_core.discovery import is_valid_address

    assert is_valid_address(case["address"]) is True


@cases("discovery-peer.json", "invalid")
def test_discovery_peer_invalid(case):
    from chaincraft_core.discovery import is_valid_address

    assert is_valid_address(case["address"]) is False


@cases("discovery-peer.json", "sequence")
def test_discovery_peer_sequence(case):
    from chaincraft_core.discovery import AddressBook

    book = AddressBook(
        listen=case["listen"],
        capacity=case["capacity"],
        timeout_ms=load("discovery-peer.json")["default_timeout_ms"],
    )
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        op = step["op"]
        if op == "insert":
            assert book.insert(step["address"], step["now_ms"]) is step["added"], where
        elif op == "ingest":
            assert book.ingest(step["addresses"], step["now_ms"], step["solicited"]) == step["added"], where
        elif op == "sweep":
            assert book.sweep(step["now_ms"]) == step["expired"], where
        elif op == "advertise":
            assert book.advertise() == step["advertised"], where
        else:
            raise AssertionError(f"unknown op {op}")
        assert len(book) == step["size"], where
        assert book.addresses() == step["book"], where
        assert book.advertise() == step["advertised"], where


@cases("discovery-local.json", "sequence")
def test_discovery_local_sequence(case):
    from chaincraft_core.discovery import AddressBook, LocalDiscovery

    book = AddressBook(listen=case["listen"])
    local = LocalDiscovery(book, enabled=case["enabled"])
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        op = step["op"]
        if op == "insert":
            assert book.insert(step["address"], step["now_ms"]) is step["added"], where
        elif op == "request":
            assert local.request(step["peer"]) is step["ok"], where
            assert book.is_solicited(step["peer"]) is step["solicited"], where
        elif op == "reply":
            assert local.reply() == step["peers"], where
        elif op == "accept":
            assert local.accept(step["from"], step["addresses"], step["now_ms"]) == step["added"], where
            assert book.is_solicited(step["from"]) is step["solicited"], where
        else:
            raise AssertionError(f"unknown op {op}")
        assert len(book) == step["size"], where
        assert book.addresses() == step["book"], where
        assert book.advertise() == step["advertised"], where


# --- Level 2 consensus ------------------------------------------------------


@cases("consensus-pow.json", "replay")
def test_consensus_pow_replay(case):
    from chaincraft_core.consensus_pow import ProofOfWork

    obj = ProofOfWork(load("consensus-pow.json")["difficulty"])
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "blocks": step["blocks"],
            "height": step["height"],
            "tip": step["tip"],
        }, where


@cases("consensus-pos.json", "schedule")
def test_consensus_pos_schedule(case):
    from chaincraft_core.consensus_pos import ProofOfStake

    doc = load("consensus-pos.json")
    obj = ProofOfStake(seed=doc["seed"], validators=doc["validators"])
    assert obj.proposer(case["slot"]) == case["proposer"]


@cases("consensus-pos.json", "replay")
def test_consensus_pos_replay(case):
    from chaincraft_core.consensus_pos import ProofOfStake

    obj = ProofOfStake()
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "head": step["head"],
            "last_proposer": step["last_proposer"],
            "slot": step["slot"],
        }, where


@cases("consensus-pbft.json", "replay")
def test_consensus_pbft_replay(case):
    from chaincraft_core.consensus_pbft import PBFT

    obj = PBFT()
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "commits": step["commits"],
            "executed": step["executed"],
            "prepares": step["prepares"],
            "sequence": step["sequence"],
            "view": step["view"],
        }, where


# --- Level 2 ledgers --------------------------------------------------------


@cases("ledger-balance.json", "replay")
def test_ledger_balance_replay(case):
    from chaincraft_core.ledger_balance import BalanceLedger

    obj = BalanceLedger(load("ledger-balance.json")["allocations"])
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "balances": step["balances"],
            "burned": step["burned"],
            "nonces": step["nonces"],
            "supply": step["supply"],
        }, where


@cases("ledger-utxo.json", "replay")
def test_ledger_utxo_replay(case):
    from chaincraft_core.ledger_utxo import UtxoLedger

    obj = UtxoLedger(load("ledger-utxo.json")["allocations"])
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "burned": step["burned"],
            "supply": step["supply"],
            "utxos": step["utxos"],
        }, where


# --- Level 2 mempool and fees -----------------------------------------------


@cases("mempool-basic.json", "sequence")
def test_mempool_basic_sequence(case):
    from chaincraft_core.mempool import Mempool

    pool = Mempool(
        capacity=case["capacity"],
        min_fee=case["min_fee"],
        ttl_ms=case["ttl_ms"],
        max_per_sender=case["max_per_sender"],
        rbf_min_increase=case["rbf_min_increase"],
    )
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        op = step["op"]
        if op == "insert":
            result = pool.insert(step["tx"], step["now_ms"])
            assert result["accepted"] is step["accepted"], where
            assert result["replaced"] == step["replaced"], where
            assert result["evicted"] == step["evicted"], where
            assert result["expired"] == step["expired"], where
        elif op == "remove":
            assert pool.remove(step["id"]) is step["removed"], where
        elif op == "sweep":
            assert pool.sweep(step["now_ms"]) == step["expired"], where
        else:
            raise AssertionError(f"unknown op {op}")
        assert pool.ids() == step["ids"], where
        assert len(pool) == step["size"], where


@cases("fees-policy.json", "select")
def test_fees_policy_select(case):
    from chaincraft_core.fees import select

    assert select(case["candidates"], case["limit"]) == case["ids"]


@cases("fees-policy.json", "charge")
def test_fees_policy_charge(case):
    from chaincraft_core.fees import charge

    assert charge(case["fee"], case["base"]) == {
        "burned": case["burned"],
        "charged": case["charged"],
        "tip": case["tip"],
    }


@cases("fees-policy.json", "estimate")
def test_fees_policy_estimate(case):
    from chaincraft_core.fees import estimate

    assert estimate(case["fees"]) == case["estimate"]


@cases("fees-policy.json", "base_fee")
def test_fees_policy_base_fee(case):
    from chaincraft_core.fees import next_base_fee

    assert next_base_fee(case["base"], case["parent_count"], case["target"]) == case["next"]


# --- vector hygiene ---------------------------------------------------------


def test_every_vector_file_declares_its_feature():
    files = sorted(VECTORS.glob("*.json"))
    assert files, "no vectors generated"
    for path in files:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        for field in ("feature", "spec", "wire_version", "generator"):
            assert field in data, f"{path.name} is missing {field!r}"
        assert data["wire_version"] == 1


def test_vectors_are_reproducible():
    """Regenerating must be a no-op, or vector diffs stop meaning anything."""
    import subprocess
    import sys

    repo = VECTORS.parent.parent
    before = {p.name: p.read_bytes() for p in sorted(VECTORS.glob("*.json"))}
    result = subprocess.run(
        [sys.executable, "conformance/generate_vectors.py"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    after = {p.name: p.read_bytes() for p in sorted(VECTORS.glob("*.json"))}
    assert before == after, "generator is not deterministic"
