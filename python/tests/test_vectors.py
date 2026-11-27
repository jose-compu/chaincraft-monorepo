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

from chaincraft import control, crypto, framing
from chaincraft.canonical import (
    CanonicalError,
    canonical_json,
    parse_json,
    payload_digest,
)
from chaincraft.dedup import Deduplicator
from chaincraft.envelope import Envelope, ProtocolError
from chaincraft.framing import FrameReader, FramingError, encode_frame
from chaincraft.memento import StateMemento
from chaincraft.object import frontier_digest, merkle_digest, wins_replacement

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
    assert (
        Envelope.parse(case["canonical"], now_ms=load("envelope.json")["now_ms"]) == env
    )


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


# --- wire.paths -------------------------------------------------------------


@cases("wire-paths.json", "classify")
def test_wire_paths(case):
    env = Envelope.build(case["type"], {"n": 1}, ts=case["ts"])
    assert env.path() == case["path"]
    assert env.is_control() is (case["path"] == "control")
    dedup = Deduplicator()
    assert dedup.should_process(env) is case["first_process"]
    assert dedup.should_process(env) is case["repeat_process"]
    assert dedup.should_relay(env) is case["relay"]
    assert len(dedup.seen) == case["seen_size"]


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
    from chaincraft import ecdsa

    key = bytes.fromhex(case["secret_key"])
    message = bytes.fromhex(case["message_hex"])
    assert ecdsa.public_key(key).hex() == case["public_key"]
    assert ecdsa.sign(message, key).hex() == case["signature"]
    assert ecdsa.verify(
        message, bytes.fromhex(case["signature"]), bytes.fromhex(case["public_key"])
    )


@cases("ecdsa.json", "invalid")
def test_ecdsa_invalid(case):
    from chaincraft import ecdsa

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
    from chaincraft import vdf

    proof = vdf.evaluate(bytes.fromhex(case["seed_hex"]), case["t"])
    assert vdf.proof_to_hex(proof) == case["proof"]
    assert vdf.verify(bytes.fromhex(case["seed_hex"]), case["t"], proof)


@cases("vdf.json", "invalid")
def test_vdf_invalid(case):
    from chaincraft import vdf

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
    from chaincraft import vrf

    proof, output, pk = vrf.evaluate(
        bytes.fromhex(case["message_hex"]), bytes.fromhex(case["secret_key"])
    )
    assert pk.hex() == case["public_key"]
    assert proof.hex() == case["proof"]
    assert output.hex() == case["output"]
    assert vrf.verify(bytes.fromhex(case["message_hex"]), proof, pk, output)


@cases("vrf.json", "invalid")
def test_vrf_invalid(case):
    from chaincraft import vrf

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
    from chaincraft.discovery import is_valid_address

    assert is_valid_address(case["address"]) is True


@cases("discovery-peer.json", "invalid")
def test_discovery_peer_invalid(case):
    from chaincraft.discovery import is_valid_address

    assert is_valid_address(case["address"]) is False


@cases("discovery-peer.json", "connect")
def test_discovery_peer_connect(case):
    from chaincraft.discovery import is_connect_allowed

    assert is_connect_allowed(case["address"]) is case["allowed"]


@cases("discovery-peer.json", "sequence")
def test_discovery_peer_sequence(case):
    from chaincraft.discovery import AddressBook

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
            assert (
                book.ingest(step["addresses"], step["now_ms"], step["solicited"])
                == step["added"]
            ), where
        elif op == "sweep":
            assert book.sweep(step["now_ms"]) == step["expired"], where
        elif op == "advertise":
            assert book.advertise() == step["advertised"], where
        else:
            raise AssertionError(f"unknown op {op}")
        assert len(book) == step["size"], where
        assert book.addresses() == step["book"], where
        assert book.advertise() == step["advertised"], where


@cases("discovery-ban.json", "sequence")
def test_discovery_ban_sequence(case):
    from chaincraft.ban import BanSet, classify_inbound

    base = 1757430000000
    bs = BanSet(strike_limit=case["strike_limit"], ban_ttl_ms=case["ban_ttl_ms"])
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        op = step["op"]
        if op == "note":
            now_ms = step.get("now_ms", base)
            if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < 0:
                result = "ignored"
            else:
                result = bs.note(step["peer"], step["reason"], now_ms)
            assert result == step["result"], where
            if "strikes" in step:
                assert bs.strikes(step["peer"]) == step["strikes"], where
        elif op == "strikes":
            assert bs.strikes(step["peer"]) == step["strikes"], where
        elif op == "banned":
            clock = step.get("now_ms", base)
            assert bs.banned(clock) == step["banned"], where
        elif op == "is_banned":
            peer = step["peer"]
            clock = step["now_ms"]
            expect = peer in step["banned"]
            assert bs.is_banned(peer, clock) is expect, where
        else:
            raise AssertionError(f"unknown op {op}")
        clock = step.get("now_ms", base)
        if isinstance(clock, bool):
            clock = base
        state = bs.state(clock)
        assert state["size"] == step["size"], where
        assert state["banned"] == step["banned"], where
        assert state["tracked"] == step["tracked"], where
    for index, row in enumerate(case["classify"]):
        where = f"classify {index}"
        out = classify_inbound(
            row["type"], row["solicited"], row["duplicate"], row["address_ok"]
        )
        assert out["action"] == row["action"], where
        assert out["reason"] == row["reason"], where
        state = bs.state(base)
        assert state["size"] == row["size"], where
        assert state["banned"] == row["banned"], where
        assert state["tracked"] == row["tracked"], where


@cases("discovery-local.json", "sequence")
def test_discovery_local_sequence(case):
    from chaincraft.discovery import AddressBook, LocalDiscovery

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
            assert (
                local.accept(step["from"], step["addresses"], step["now_ms"])
                == step["added"]
            ), where
            assert book.is_solicited(step["from"]) is step["solicited"], where
        else:
            raise AssertionError(f"unknown op {op}")
        assert len(book) == step["size"], where
        assert book.addresses() == step["book"], where
        assert book.advertise() == step["advertised"], where


# --- Level 2 consensus ------------------------------------------------------


@cases("consensus-poa.json", "replay")
def test_consensus_poa_replay(case):
    from chaincraft.consensus_poa import ProofOfAuthority

    authorities = load("consensus-poa.json")["authorities"]
    obj = ProofOfAuthority(authorities)
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "blocks": step["blocks"],
            "canonical": step["canonical"],
            "height": step["height"],
            "tip": step["tip"],
        }, where
    if "reorg_count" in case:
        reorgs = [step for step in case["steps"] if step["reorg"]]
        assert len(reorgs) == case["reorg_count"]
        assert min(step["reorg_depth"] for step in reorgs) >= case["min_reorg_depth"]


@cases("consensus-ouroboros.json", "replay")
def test_consensus_ouroboros_replay(case):
    from chaincraft.consensus_ouroboros import Ouroboros

    doc = load("consensus-ouroboros.json")
    stakeholders = [
        (s["id"], s["stake"], s["pk"]) for s in doc["stakeholders"]
    ]
    obj = Ouroboros(doc["nonce"], doc["epoch_length"], stakeholders)
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "slot": step["slot"],
            "tip": step["tip"],
            "canonical": step["canonical"],
            "blocks": step["blocks"],
            "epoch": step["epoch"],
            "nonce": step["nonce"],
        }, where
    if "reorg_count" in case:
        reorgs = [step for step in case["steps"] if step.get("reorg")]
        assert len(reorgs) == case["reorg_count"]
        assert min(step["reorg_depth"] for step in reorgs) >= case["min_reorg_depth"]


@cases("consensus-pox.json", "replay")
def test_consensus_pox_replay(case):
    from chaincraft.consensus_pox import ProofOfTransfer

    doc = load("consensus-pox.json")
    stackers = [(s["locker"], s["amount"]) for s in doc["stackers"]]
    obj = ProofOfTransfer(doc["seed"], doc["cycle_length"], stackers)
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "height": step["height"],
            "tip": step["tip"],
            "open_height": step["open_height"],
            "cycle": step["cycle"],
            "canonical": step["canonical"],
            "tenures": step["tenures"],
            "bids": step["bids"],
            "stacks": step["stacks"],
        }, where


@cases("consensus-beacon.json", "replay")
def test_consensus_beacon_replay(case):
    from chaincraft.consensus_beacon import RandomnessBeacon

    obj = RandomnessBeacon()
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "canonical": step["canonical"],
            "height": step["height"],
            "output": step["output"],
            "pulses": step["pulses"],
        }, where


def test_consensus_beacon_constructor():
    from chaincraft import canonical_json, vrf
    from chaincraft.consensus_beacon import (
        GENESIS_PREVIOUS,
        RandomnessBeacon,
        pulse_id,
    )

    empty = RandomnessBeacon()
    assert (
        empty.emit_state_memento().canonical_digest
        == "b3d1cf3908c77c7645bf1bb5daf96e02d92038c62ffb771aec69d247f965f549"
    )
    sk = bytes.fromhex(
        "0000000000000000000000000000000000000000000000000000000000000003"
    )
    msg = canonical_json({"height": 0, "previous": GENESIS_PREVIOUS}).encode("utf-8")
    proof, output, pk = vrf.evaluate(msg, sk)
    pulse = {
        "consensus": "beacon",
        "height": 0,
        "previous": GENESIS_PREVIOUS,
        "pk": pk.hex(),
        "proof": proof.hex(),
        "output": output.hex(),
    }
    assert (
        pulse_id(
            pulse["height"],
            pulse["output"],
            pulse["pk"],
            pulse["previous"],
            pulse["proof"],
        )
        == load("consensus-beacon.json")["genesis_id"]
    )
    fresh = RandomnessBeacon()
    assert fresh.is_valid(pulse)
    fresh.add_message(pulse)
    assert fresh.state()["height"] == 0
    assert fresh.state()["output"] == pulse["output"]


@cases("consensus-poet.json", "replay")
def test_consensus_poet_replay(case):
    from chaincraft.consensus_poet import ProofOfElapsedTime

    seed = load("consensus-poet.json")["seed"]
    obj = ProofOfElapsedTime(seed)
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.state() == {
            "canonical": step["canonical"],
            "tickets": step["tickets"],
            "wait": step["wait"],
            "winner": step["winner"],
        }, where


def test_consensus_poet_constructor():
    from chaincraft.consensus_poet import ProofOfElapsedTime, ticket_id
    from chaincraft import vdf

    with pytest.raises(ValueError):
        ProofOfElapsedTime("")
    empty = ProofOfElapsedTime("poet-round")
    assert (
        empty.emit_state_memento().canonical_digest
        == "b937f65d3e33b1d2041b879a146f6ab092b2f1d3ff5a228ed1d9bf42268d357f"
    )
    proof = vdf.proof_to_hex(vdf.evaluate(b"poet-round", 2))
    msg = {
        "author": "alice",
        "consensus": "poet",
        "payload": "one",
        "proof": proof,
        "wait": 2,
    }
    fresh = ProofOfElapsedTime("poet-round")
    assert fresh.is_valid(msg)
    fresh.add_message(msg)
    assert (
        fresh.emit_state_memento().canonical_digest
        == "671e91205e93cc18534c619c1caf6fdd469e1bdfbeb468dd65f43287c5315eb4"
    )
    bob = {
        "author": "bob",
        "consensus": "poet",
        "payload": "two",
        "proof": vdf.proof_to_hex(vdf.evaluate(b"poet-round", 1)),
        "wait": 1,
    }
    fresh.add_message(bob)
    assert (
        fresh.emit_state_memento().canonical_digest
        == "fd8a92143478eff67f0132fbc0fa293509ec06911fb41a0f61d1baffb7f84a04"
    )
    assert (
        ticket_id("alice", "one", proof, 2) == load("consensus-poet.json")["alice_id"]
    )


def test_consensus_poa_constructor():
    from chaincraft.consensus_poa import ProofOfAuthority, proposer_for

    with pytest.raises(ValueError):
        ProofOfAuthority([])
    with pytest.raises(ValueError):
        ProofOfAuthority(["alice", "alice"])
    with pytest.raises(ValueError):
        ProofOfAuthority(["alice", ""])
    solo = ProofOfAuthority(["solo"])
    assert proposer_for(1, solo.authorities) == "solo"
    assert proposer_for(2, solo.authorities) == "solo"
    msg1 = {
        "consensus": "poa",
        "height": 1,
        "parent": "",
        "payload": "a",
        "proposer": "solo",
    }
    assert solo.is_valid(msg1)
    solo.add_message(msg1)
    msg2 = {
        "consensus": "poa",
        "height": 2,
        "parent": solo.state()["tip"],
        "payload": "b",
        "proposer": "solo",
    }
    assert solo.is_valid(msg2)
    solo.add_message(msg2)
    assert solo.state()["height"] == 2


@cases("consensus-pow.json", "replay")
def test_consensus_pow_replay(case):
    from chaincraft.consensus_pow import ProofOfWork

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
            "canonical": step["canonical"],
            "height": step["height"],
            "tip": step["tip"],
        }, where
    if "reorg_count" in case:
        reorgs = [step for step in case["steps"] if step["reorg"]]
        assert len(reorgs) == case["reorg_count"]
        assert min(step["reorg_depth"] for step in reorgs) >= case["min_reorg_depth"]


@cases("consensus-pos.json", "schedule")
def test_consensus_pos_schedule(case):
    from chaincraft.consensus_pos import ProofOfStake

    doc = load("consensus-pos.json")
    obj = ProofOfStake(seed=doc["seed"], validators=doc["validators"])
    assert obj.proposer(case["slot"]) == case["proposer"]


@cases("consensus-pos.json", "replay")
def test_consensus_pos_replay(case):
    from chaincraft.consensus_pos import ProofOfStake

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
    from chaincraft.consensus_pbft import PBFT

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


@cases("consensus-avalanche.json", "replay")
def test_consensus_avalanche_replay(case):
    from chaincraft.consensus_avalanche import Avalanche

    obj = Avalanche(case["steps"][0]["phase"])
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"{case['name']} step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            obj.add_message(message)
        assert obj.is_merkelized() is True, where
        assert obj.state() == {
            "cnt": step["cnt"],
            "d": step["d"],
            "final": step["final"],
            "phase": step["phase"],
            "pref": step["pref"],
            "rounds": step["rounds"],
        }, where


# --- Level 2 ledgers --------------------------------------------------------


@cases("ledger-balance.json", "replay")
def test_ledger_balance_replay(case):
    from chaincraft.ledger_balance import BalanceLedger

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
    from chaincraft.ledger_utxo import UtxoLedger

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
    from chaincraft.mempool import Mempool

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
    from chaincraft.fees import select

    assert select(case["candidates"], case["limit"]) == case["ids"]


@cases("fees-policy.json", "charge")
def test_fees_policy_charge(case):
    from chaincraft.fees import charge

    assert charge(case["fee"], case["base"]) == {
        "burned": case["burned"],
        "charged": case["charged"],
        "tip": case["tip"],
    }


@cases("fees-policy.json", "estimate")
def test_fees_policy_estimate(case):
    from chaincraft.fees import estimate

    assert estimate(case["fees"]) == case["estimate"]


@cases("fees-policy.json", "base_fee")
def test_fees_policy_base_fee(case):
    from chaincraft.fees import next_base_fee

    assert (
        next_base_fee(case["base"], case["parent_count"], case["target"])
        == case["next"]
    )


# --- Level 2 storage and CLI ------------------------------------------------


@cases("storage-index.json", "sequence")
def test_storage_index_sequence(case):
    from chaincraft.storage import MessageStore

    store = MessageStore(case["capacity"])
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        op = step["op"]
        if op == "register":
            assert store.register(step["type"], step["field"]) is step["ok"], where
        elif op == "put":
            assert store.put(step["id"], step["body"]) is step["added"], where
        elif op == "query":
            assert (
                store.query(step["type"], step["field"], step["value"]) == step["hits"]
            ), where
        elif op == "remove":
            assert store.remove(step["id"]) is step["removed"], where
        elif op == "load":
            assert store.load(step["snapshot"]) is step["ok"], where
        else:
            raise AssertionError(f"unknown op {op}")
        assert store.ids() == step["ids"], where
        assert len(store) == step["size"], where
        assert store.dump() == step["dump"], where


@cases("storage-persistent.json", "sequence")
def test_storage_persistent_sequence(case):
    from chaincraft.storage import MessageStore

    store = MessageStore(case["capacity"])
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        op = step["op"]
        if op == "put":
            assert store.put(step["id"], step["body"]) is step["added"], where
        elif op == "get":
            assert store.get(step["id"]) == {
                "body": step["body"],
                "found": step["found"],
            }, where
        elif op == "remove":
            assert store.remove(step["id"]) is step["removed"], where
        elif op == "load":
            assert store.load(step["snapshot"]) is step["ok"], where
        else:
            raise AssertionError(f"unknown op {op}")
        assert store.ids() == step["ids"], where
        assert len(store) == step["size"], where
        assert store.dump() == step["dump"], where


@cases("cli-node.json", "sequence")
def test_cli_node_sequence(case):
    from chaincraft.cli import NodeSession

    session = NodeSession(case["impl"], case["listen"])
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        op = step["op"]
        if op == "start":
            events = session.start()
        elif op == "line":
            events = session.handle(step["line"])
        else:
            raise AssertionError(f"unknown op {op}")
        assert events == step["events"], where
        assert session.state() == {
            "closed": step["closed"],
            "ids": step["ids"],
            "peers": step["peers"],
        }, where


# --- Level 2 channel --------------------------------------------------------


@cases("wire-channel.json", "parse")
def test_wire_channel_parse(case):
    from chaincraft.channel import parse_address

    assert parse_address(case["input"]) == {
        "ok": case["ok"],
        "scheme": case["scheme"],
        "canonical": case["canonical"],
        "cap": case["cap"],
    }


@cases("wire-channel.json", "connect")
def test_wire_channel_connect(case):
    from chaincraft.channel import is_connect_allowed

    assert is_connect_allowed(case["input"]) is case["allowed"]


@cases("wire-channel.json", "sequence")
def test_wire_channel_sequence(case):
    from chaincraft.channel import LoopBus, LoopChannel

    bus = LoopBus()
    peers = {"a": LoopChannel(bus), "b": LoopChannel(bus)}
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        actor = peers[step["who"]]
        op = step["op"]
        if op == "listen":
            assert actor.listen(step["addr"]) is step["ok"], where
        elif op == "dial":
            assert actor.dial(step["addr"]) is step["ok"], where
        elif op == "send":
            assert actor.send(step["addr"], step["data"]) is step["ok"], where
        elif op == "recv":
            assert actor.recv() == step["returned"], where
        elif op == "close":
            actor.close()
        else:
            raise AssertionError(f"unknown op {op}")
        assert actor.listen_addr == step[f"{step['who']}_listen"], where
        assert peers["a"].listen_addr == step["a_listen"], where
        assert peers["b"].listen_addr == step["b_listen"], where
        assert peers["a"].inbox() == step["a_inbox"], where
        assert peers["b"].inbox() == step["b_inbox"], where


# --- Level 2 channel adapters -----------------------------------------------


@cases("channel-adapters.json", "sequence")
def test_channel_adapters_sequence(case):
    from chaincraft.adapters import (
        AdapterChannel,
        forum_bus,
        mail_bus,
        pipe_bus,
        udp_bus,
        webrtc_bus,
    )

    buses = {
        "udp": udp_bus,
        "mailto": mail_bus,
        "webrtc": webrtc_bus,
        "forum": forum_bus,
        "pipe": pipe_bus,
    }
    bus = buses[case["scheme"]]()
    peers = {"a": AdapterChannel(bus), "b": AdapterChannel(bus)}
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        actor = peers[step["who"]]
        op = step["op"]
        if op == "listen":
            assert actor.listen(step["addr"]) is step["ok"], where
        elif op == "dial":
            assert actor.dial(step["addr"]) is step["ok"], where
        elif op == "send":
            assert actor.send(step["addr"], step["data"]) is step["ok"], where
        elif op == "recv":
            assert actor.recv() == step["returned"], where
        elif op == "close":
            actor.close()
        else:
            raise AssertionError(f"unknown op {op}")
        assert peers["a"].listen_addr == step["a_listen"], where
        assert peers["b"].listen_addr == step["b_listen"], where
        assert peers["a"].inbox() == step["a_inbox"], where
        assert peers["b"].inbox() == step["b_inbox"], where


# --- Level 2 BitTorrent -----------------------------------------------------


@cases("bittorrent-swarm.json", "replay")
def test_bittorrent_swarm_replay(case):
    from chaincraft.bittorrent import Swarm

    obj = Swarm()
    digest = case["info_hash"]
    for index, step in enumerate(case["steps"]):
        where = f"step {index}"
        accepted = obj.is_valid(step["message"])
        assert accepted is step["accepted"], where
        if accepted:
            assert obj.add_message(step["message"]) is None, where
        assert obj.is_merkelized() is False, where
        memo = obj.emit_state_memento()
        assert memo.canonical_digest == "" and memo.frontier_digests == [], where
        assert obj.assembled(digest) == step["assembled"], where
        assert obj.state() == step["state"], where


# --- Level 2 NAT ------------------------------------------------------------


@cases("discovery-nat.json", "request")
def test_nat_request(case):
    from chaincraft.nat import binding_request

    assert binding_request(case["txid"]) == {"ok": case["ok"], "packet": case["packet"]}


@cases("discovery-nat.json", "success")
def test_nat_success(case):
    from chaincraft.nat import binding_success

    assert binding_success(case["txid"], case["host"], case["port"]) == {
        "ok": case["ok"],
        "packet": case["packet"],
    }


@cases("discovery-nat.json", "response")
def test_nat_response(case):
    from chaincraft.nat import parse_binding_response

    assert parse_binding_response(case["packet"], case["txid"]) == {
        "ok": case["ok"],
        "host": case["host"],
        "port": case["port"],
    }


@cases("discovery-nat.json", "construct")
def test_nat_construct(case):
    from chaincraft.nat import NatTraversal

    if not case["ok"]:
        with pytest.raises(ProtocolError):
            NatTraversal(case["listen"], external=case["external"], relay=case["relay"])
        return
    node = NatTraversal(case["listen"], external=case["external"], relay=case["relay"])
    assert node.advertise() == case["advertise"]


@cases("discovery-nat.json", "sequence")
def test_nat_sequence(case):
    from chaincraft.nat import NatTraversal

    node = NatTraversal(case["listen"], external=case["external"], relay=case["relay"])
    for index, step in enumerate(case["steps"]):
        where = f"step {index} ({step['op']})"
        op = step["op"]
        if op == "arm":
            assert node.arm(step["transport"]) is step["ok"], where
        elif op == "observe_stun":
            assert node.observe_stun(step["packet"], step["txid"]) is step["ok"], where
        elif op == "punch":
            assert node.punch(step["peer"]) == {
                "ok": step["ok"],
                "datagram": step["datagram"],
                "addr": step["addr"],
            }, where
        elif op == "observe_punch":
            assert (
                node.observe_punch(step["datagram"], step["from"]) is step["ok"]
            ), where
        elif op == "relay_request":
            assert node.relay_request(step["target"]) == {
                "ok": step["ok"],
                "message": step["message"],
            }, where
        elif op == "handle":
            assert node.handle(step["message"]) == {
                "ok": step["ok"],
                "action": step["action"],
                "addr": step["addr"],
                "reply": step["reply"],
            }, where
        else:
            raise AssertionError(f"unknown op {op}")
        assert node.advertise() == step["advertise"], where
        assert node.armed() is step["armed"], where
        assert node.external_address() == step["external"], where
        assert node.opened() == step["opened"], where


# --- Level 2 publish-subscribe ----------------------------------------------


@cases("app-pubsub.json", "replay")
def test_app_pubsub_replay(case):
    from chaincraft.pubsub import PubSub

    obj = PubSub()
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"{case['name']} step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            assert obj.add_message(message) is None, where
        assert obj.is_merkelized() is False, where
        assert obj.get_state_digests() == [], where
        memo = obj.emit_state_memento()
        assert memo.canonical_digest == "", where
        assert memo.frontier_digests == [], where
        assert obj.state() == {"rooms": step["rooms"]}, where


@cases("protocol-crdt-kv.json", "replay")
def test_protocol_crdt_kv_replay(case):
    from chaincraft.crdt import CrdtKv

    obj = CrdtKv()
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"{case['name']} step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            assert obj.add_message(message) is None, where
        assert obj.is_merkelized() is False, where
        assert obj.get_state_digests() == [], where
        assert obj.state() == {"keys": step["keys"]}, where


# --- Level 2 event stream ---------------------------------------------------


@cases("app-stream.json", "replay")
def test_app_stream_replay(case):
    from chaincraft.stream import Stream

    obj = Stream()
    for index, step in enumerate(case["steps"]):
        message = parse_json(step["message_json"])
        where = f"{case['name']} step {index}"
        accepted = obj.is_valid(message)
        assert accepted is step["accepted"], where
        if accepted:
            assert obj.add_message(message) is None, where
        assert obj.is_merkelized() is False, where
        assert obj.get_state_digests() == [], where
        memo = obj.emit_state_memento()
        assert memo.canonical_digest == "", where
        assert memo.frontier_digests == [], where
        assert obj.state() == {"streams": step["streams"]}, where
        for probe in step.get("reads", []):
            assert (
                obj.read(
                    probe["stream"], probe["partition"], probe["after"], probe["limit"]
                )
                == probe["events"]
            ), where


def test_channel_peer_transcript():
    from chaincraft.peer import (
        DEFAULT_PEER_ORIGIN,
        EnvelopeRelay,
        parse_peer_id_body,
        peer_options,
    )

    doc = load("channel-peer.json")
    assert doc["origin"] == DEFAULT_PEER_ORIGIN
    assert peer_options() == doc["options"]
    for case in doc["ids"]:
        assert parse_peer_id_body(case["input"]) == case["id"], case["name"]
    relay = EnvelopeRelay()
    for step in doc["steps"]:
        if step["op"] == "join":
            assert relay.join(step["addr"]) is step["ok"], step["addr"]
        elif step["op"] == "publish":
            assert (
                relay.publish(step["src"], step["type"], json.loads(step["data"]))
                == step["id"]
            ), step["src"]
        elif step["op"] == "take":
            assert relay.take(step["addr"]) == step["inbox"], step["addr"]
        else:
            raise AssertionError(step["op"])


def test_channel_hybrid_transcript():
    from chaincraft.hybrid import LinkMesh, hello_caps

    doc = load("channel-hybrid.json")
    assert hello_caps(False) == doc["caps_tcp"]
    assert hello_caps(True) == doc["caps_udp"]
    mesh = LinkMesh()
    for step in doc["steps"]:
        if step["op"] == "join":
            assert mesh.join(step["addr"]) is step["ok"], step["addr"]
        elif step["op"] == "gossip":
            assert (
                mesh.gossip(step["src"], step["type"], json.loads(step["data"]))
                == step["id"]
            ), step["src"]
        elif step["op"] == "direct":
            assert (
                mesh.direct(
                    step["src"], step["dst"], step["type"], json.loads(step["data"])
                )
                == step["id"]
            ), step["dst"]
        elif step["op"] == "take":
            assert mesh.take(step["addr"]) == step["inbox"], step["addr"]
        else:
            raise AssertionError(step["op"])


# --- Level 2 transfer chain -------------------------------------------------


@cases("chain-transfer.json", "replay")
def test_chain_transfer_replay(case):
    from chaincraft.chain import TransferChain
    from chaincraft.chain_driver import make_driver

    genesis = load("chain-transfer.json")["genesis"]
    driver = make_driver(case["consensus"], **case.get("options", {}))
    chain = TransferChain(genesis, reward=case["reward"], driver=driver)
    for index, step in enumerate(case["steps"]):
        where = f"{case['name']} step {index}"
        op = step["op"]
        if op == "submit":
            message = parse_json(step["message_json"])
            accepted = chain.submit(message)
            assert accepted is step["accepted"], where
        elif op == "produce":
            block = chain.produce(step["time"], step["producer"])
            accepted = block is not None
            assert accepted is step["accepted"], where
        elif op == "accept_block":
            block = parse_json(step["block_json"])
            accepted = chain.accept_block(block)
            assert accepted is step["accepted"], where
        else:
            raise AssertionError(f"unknown op {op}")
        st = chain.state()
        assert st["balances"] == step["balances"], where
        assert st["nonces"] == step["nonces"], where
        assert st["canonical"] == step["canonical"], where
        assert st["height"] == step["height"], where
        assert st["tip"] == step["tip"], where


def test_node_preset_replay():
    from chaincraft import preset
    from chaincraft.chain import TransferChain
    from chaincraft.chain_driver import make_driver

    doc = load("node-preset.json")
    handle = preset.start(doc["valid_config"])
    assert handle["listen_addr"].startswith(doc["valid_listen_prefix"])
    valid = doc["valid_config"]
    driver = make_driver(valid["consensus"], authorities=valid["authorities"])
    chain = TransferChain(valid["genesis"], reward=valid["reward"], driver=driver)
    block = chain.produce(1, "alice")
    assert canonical_json(block) == canonical_json(doc["hand_built_block"]), (
        "hand-built block"
    )
    handle["close"]()
    for item in doc["rejections"]:
        try:
            preset.start(item["config"])
        except ValueError as err:
            assert item["error"] in str(err), item["error"]
        else:
            raise AssertionError(f"expected preset error {item['error']!r}")
    for item in doc.get("states", []):
        state_handle = preset.start(item["config"])
        assert canonical_json(state_handle["state"]()) == canonical_json(
            item["state"]
        ), item["name"]
        state_handle["close"]()
    for item in doc.get("probes", []):
        probe = preset.start(item["config"])
        accepted = probe["submit"](item["message"])
        assert accepted == item["accepted"], item["name"]
        probe["close"]()


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
