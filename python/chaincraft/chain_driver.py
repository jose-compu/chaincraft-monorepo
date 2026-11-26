"""Consensus drivers for chain.transfer — SPEC/features/chain-transfer.md."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import vdf, vrf
from .chain import block_id
from .consensus_avalanche import Avalanche
from .consensus_beacon import GENESIS_PREVIOUS, RandomnessBeacon
from .consensus_ouroboros import Ouroboros, block_id as ouro_block_id, eligible
from .consensus_pbft import PBFT
from .consensus_poa import ProofOfAuthority, block_id as poa_block_id, proposer_for
from .consensus_poet import ProofOfElapsedTime, ticket_id as poet_ticket_id
from .consensus_pos import ProofOfStake, proposer_for as pos_proposer_for
from .consensus_pow import ProofOfWork, block_id as pow_block_id, meets_work
from .consensus_pox import ProofOfTransfer, sortition_score
from .object import merkle_digest


def make_driver(consensus: str, **options: Any) -> Any:
    name = consensus.lower()
    if name == "pow":
        return PowDriver(options.get("difficulty", 1))
    if name == "poa":
        authorities = options.get("authorities") or ["alice"]
        return PoaDriver(authorities)
    if name == "pos":
        return PosDriver()
    if name == "pbft":
        replicas = options.get("replicas")
        return PbftDriver(replicas)
    if name == "poet":
        seed = options.get("seed", "chaincraft-poet-genesis")
        return PoetDriver(seed)
    if name == "avalanche":
        return AvalancheDriver()
    if name == "beacon":
        sk = options.get("sk")
        if isinstance(sk, str):
            sk = bytes.fromhex(sk)
        return BeaconDriver(options.get("name", "alice"), sk)
    if name == "pox":
        return PoxDriver()
    if name == "ouroboros":
        return OuroborosDriver()
    raise ValueError(f"unknown consensus: {consensus}")


class _BaseDriver:
    def __init__(self) -> None:
        self._chain_to_consensus: Dict[str, str] = {}
        self._consensus_to_chain: Dict[str, str] = {}

    def _remember(self, chain_id: str, consensus_id: str) -> None:
        self._chain_to_consensus[chain_id] = consensus_id
        self._consensus_to_chain[consensus_id] = chain_id

    def _pow_parent(self, chain_parent: str) -> str:
        if not chain_parent:
            return ""
        return self._chain_to_consensus.get(chain_parent, "")


class PowDriver(_BaseDriver):
    def __init__(self, difficulty: int = 1) -> None:
        super().__init__()
        self.difficulty = difficulty
        self.pow = ProofOfWork(difficulty)

    def build_proof(self, block: Dict[str, Any]) -> Dict[str, Any]:
        header = block["header"]
        cid = block_id(header)
        parent = self._pow_parent(header["parent"])
        height = header["height"]
        nonce = 0
        while True:
            digest = pow_block_id(
                height, header["producer"], nonce, parent, cid
            )
            if meets_work(digest, self.difficulty):
                return {
                    "consensus": "pow",
                    "height": height,
                    "miner": header["producer"],
                    "nonce": nonce,
                    "parent": parent,
                    "payload": cid,
                    "id": digest,
                }
            nonce += 1

    def authorize(self, block: Dict[str, Any], proof: Any) -> bool:
        if not isinstance(proof, dict) or proof.get("consensus") != "pow":
            return False
        cid = block_id(block["header"])
        if proof.get("payload") != cid:
            return False
        if not self.pow.is_valid(proof):
            return False
        self.pow.add_message(proof)
        self._remember(cid, proof["id"])
        return True

    def canonical(self) -> List[str]:
        payloads: List[str] = []
        for digest in self.pow.state()["canonical"]:
            payloads.append(self.pow._blocks[digest]["payload"])  # noqa: SLF001
        return payloads


class PoaDriver(_BaseDriver):
    def __init__(self, authorities: Sequence[str]) -> None:
        super().__init__()
        self.authorities = list(authorities)
        self.poa = ProofOfAuthority(self.authorities)

    def build_proof(self, block: Dict[str, Any]) -> Dict[str, Any]:
        header = block["header"]
        cid = block_id(header)
        parent = self._pow_parent(header["parent"])
        proposer = header["producer"]
        return {
            "consensus": "poa",
            "height": header["height"],
            "parent": parent,
            "payload": cid,
            "proposer": proposer,
        }

    def authorize(self, block: Dict[str, Any], proof: Any) -> bool:
        if not isinstance(proof, dict) or proof.get("consensus") != "poa":
            return False
        header = block["header"]
        cid = block_id(header)
        if proof.get("payload") != cid:
            return False
        if proof.get("proposer") != proposer_for(header["height"], self.authorities):
            return False
        if not self.poa.is_valid(proof):
            return False
        self.poa.add_message(proof)
        digest = poa_block_id(
            proof["height"],
            proof["parent"],
            proof["payload"],
            proof["proposer"],
        )
        self._remember(cid, digest)
        return True

    def canonical(self) -> List[str]:
        payloads: List[str] = []
        for digest in self.poa.state()["canonical"]:
            payloads.append(self.poa._blocks[digest]["payload"])  # noqa: SLF001
        return payloads


class PosDriver(_BaseDriver):
    def __init__(self) -> None:
        super().__init__()
        self.pos = ProofOfStake()
        self._chain_ids: List[str] = []

    def build_proof(self, block: Dict[str, Any]) -> Dict[str, Any]:
        header = block["header"]
        cid = block_id(header)
        slot = header["height"]
        proposer = pos_proposer_for(slot, self.pos.seed, self.pos.validators)
        return {
            "consensus": "pos",
            "payload": cid,
            "proposer": proposer,
            "slot": slot,
        }

    def authorize(self, block: Dict[str, Any], proof: Any) -> bool:
        if not isinstance(proof, dict) or proof.get("consensus") != "pos":
            return False
        header = block["header"]
        if header["time"] != header["height"]:
            return False
        cid = block_id(header)
        if proof.get("payload") != cid:
            return False
        if not self.pos.is_valid(proof):
            return False
        self.pos.add_message(proof)
        self._chain_ids.append(cid)
        return True

    def canonical(self) -> List[str]:
        return list(self._chain_ids)


class PbftDriver(_BaseDriver):
    def __init__(self, replicas: Optional[Sequence[str]] = None) -> None:
        super().__init__()
        self.pbft = PBFT(replicas)
        self._executed: List[str] = []

    def build_proof(self, block: Dict[str, Any]) -> Dict[str, Any]:
        header = block["header"]
        cid = block_id(header)
        primary = self.pbft.primary_for(0)
        prepares = sorted(self.pbft.replicas)[: self.pbft.quorum]
        commits = list(prepares)
        return {
            "consensus": "pbft",
            "value": cid,
            "digest": merkle_digest(cid),
            "primary": primary,
            "prepares": prepares,
            "commits": commits,
        }

    def authorize(self, block: Dict[str, Any], proof: Any) -> bool:
        if not isinstance(proof, dict) or proof.get("consensus") != "pbft":
            return False
        cid = block_id(block["header"])
        value = proof.get("value")
        if value != cid:
            return False
        digest = proof.get("digest")
        if digest != merkle_digest(cid):
            return False
        primary = self.pbft.primary_for(0)
        seq = self.pbft.sequence
        msgs = [
            {
                "consensus": "pbft",
                "phase": "pre-prepare",
                "view": 0,
                "sequence": seq,
                "digest": digest,
                "replica": primary,
                "value": value,
            }
        ]
        for rep in proof.get("prepares") or []:
            msgs.append(
                {
                    "consensus": "pbft",
                    "phase": "prepare",
                    "view": 0,
                    "sequence": seq,
                    "digest": digest,
                    "replica": rep,
                }
            )
        for rep in proof.get("commits") or []:
            msgs.append(
                {
                    "consensus": "pbft",
                    "phase": "commit",
                    "view": 0,
                    "sequence": seq,
                    "digest": digest,
                    "replica": rep,
                }
            )
        for msg in msgs:
            if not self.pbft.is_valid(msg):
                return False
            self.pbft.add_message(msg)
        self._executed.append(cid)
        return True

    def canonical(self) -> List[str]:
        return list(self._executed)


class PoetDriver(_BaseDriver):
    def __init__(self, seed: str) -> None:
        super().__init__()
        self._height_seed = seed
        self._poet: Optional[ProofOfElapsedTime] = None
        self._per_height: Dict[int, ProofOfElapsedTime] = {}
        self._canonical: List[str] = []

    def _poet_for(self, header: Mapping[str, Any]) -> ProofOfElapsedTime:
        height = header["height"]
        if height not in self._per_height:
            seed = (
                self._height_seed
                if height == 1
                else header["parent"]
            )
            self._per_height[height] = ProofOfElapsedTime(seed)
        return self._per_height[height]

    def build_proof(self, block: Dict[str, Any]) -> Dict[str, Any]:
        header = block["header"]
        cid = block_id(header)
        poet = self._poet_for(header)
        wait = 1
        proof_int = vdf.evaluate(poet._seed_bytes, wait)
        proof_hex = vdf.proof_to_hex(proof_int)
        return {
            "consensus": "poet",
            "author": header["producer"],
            "payload": cid,
            "wait": wait,
            "proof": proof_hex,
        }

    def authorize(self, block: Dict[str, Any], proof: Any) -> bool:
        if not isinstance(proof, dict) or proof.get("consensus") != "poet":
            return False
        cid = block_id(block["header"])
        if proof.get("payload") != cid:
            return False
        poet = self._poet_for(block["header"])
        if not poet.is_valid(proof):
            return False
        poet.add_message(proof)
        if cid not in self._canonical:
            self._canonical.append(cid)
        return True

    def canonical(self) -> List[str]:
        return list(self._canonical)


class AvalancheDriver(_BaseDriver):
    def __init__(self) -> None:
        super().__init__()
        self._per_height: Dict[int, Avalanche] = {}
        self._canonical: List[str] = []

    def _snow(self, height: int) -> Avalanche:
        if height not in self._per_height:
            self._per_height[height] = Avalanche(
                "snowball", k=1, alpha=1, beta=1
            )
        return self._per_height[height]

    def build_proof(self, block: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "consensus": "avalanche",
            "messages": [
                {"color": "blue", "consensus": "avalanche", "op": "init"},
                {"consensus": "avalanche", "op": "round", "votes": ["blue"]},
            ],
        }

    def authorize(self, block: Dict[str, Any], proof: Any) -> bool:
        if not isinstance(proof, dict) or proof.get("consensus") != "avalanche":
            return False
        height = block["header"]["height"]
        snow = self._snow(height)
        for msg in proof.get("messages") or []:
            if not snow.is_valid(msg):
                return False
            snow.add_message(msg)
        if not snow.state().get("final"):
            return False
        cid = block_id(block["header"])
        if cid not in self._canonical:
            self._canonical.append(cid)
        return True

    def canonical(self) -> List[str]:
        return list(self._canonical)


class BeaconDriver(_BaseDriver):
    def __init__(self, name: str, sk: Optional[bytes]) -> None:
        super().__init__()
        self.name = name
        self.sk = sk
        self.beacon = RandomnessBeacon()
        self._canonical: List[str] = []
        if sk is not None:
            _, _, self._pk_hex = vrf.evaluate(b"bootstrap", sk)
            self._pk_hex = self._pk_hex.hex()

    def _pulse_message(self, height: int, previous: str) -> bytes:
        from .canonical import canonical_json

        return canonical_json({"height": height, "previous": previous}).encode("utf-8")

    def _previous_output(self) -> str:
        height, output = self.beacon._tip()  # noqa: SLF001
        if height < 0:
            return GENESIS_PREVIOUS
        return output

    def build_proof(self, block: Dict[str, Any]) -> Dict[str, Any]:
        header = block["header"]
        beacon_height = header["height"] - 1
        previous = self._previous_output()
        if self.sk is None:
            raise ValueError("beacon driver requires sk")
        message = self._pulse_message(beacon_height, previous)
        proof, output, pk = vrf.evaluate(message, self.sk)
        return {
            "consensus": "beacon",
            "height": beacon_height,
            "previous": previous,
            "pk": pk.hex(),
            "proof": proof.hex(),
            "output": output.hex(),
        }

    def authorize(self, block: Dict[str, Any], proof: Any) -> bool:
        if not isinstance(proof, dict) or proof.get("consensus") != "beacon":
            return False
        header = block["header"]
        if header["producer"] != self.name:
            return False
        if proof.get("pk") != self._pk_hex:
            return False
        expected_h = header["height"] - 1
        if proof.get("height") != expected_h:
            return False
        if not self.beacon.is_valid(proof):
            return False
        self.beacon.add_message(proof)
        self._canonical.append(block_id(header))
        return True

    def canonical(self) -> List[str]:
        return list(self._canonical)


_POX_SEED = "0123456789abcdef" * 4
_POX_CYCLE = 3
_POX_STACKERS = [("alice", 100), ("bob", 200), ("carol", 50)]
_OURO_NONCE = "0123456789abcdef" * 4
_OURO_EPOCH = 2


def _ouro_table() -> List[tuple]:
    from . import crypto as cc

    rows = []
    for sid, stake, sk in [("alice", 100, bytes(31) + b"\x03"), ("bob", 1, bytes.fromhex(
        "c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721"
    ))]:
        pk = vrf.evaluate(b"bootstrap", sk)[2].hex()
        rows.append((sid, stake, pk))
    return rows


_OURO_KEYS = {
    "alice": bytes(31) + b"\x03",
    "bob": bytes.fromhex(
        "c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721"
    ),
}


class PoxDriver(_BaseDriver):
    def __init__(self, **_: Any) -> None:
        super().__init__()
        self.pox = ProofOfTransfer(_POX_SEED, _POX_CYCLE, _POX_STACKERS)
        self._chain_ids: List[str] = []

    def _pox_elected(self, height: int) -> str:
        miners = (("alice", 5), ("bob", 6), ("carol", 4))
        best_miner = "alice"
        best_score = ""
        for miner, btc in miners:
            score = sortition_score(_POX_SEED, miner, btc, height)
            if not best_score or score < best_score:
                best_miner = miner
                best_score = score
        return best_miner

    def build_proof(self, block: Dict[str, Any]) -> Dict[str, Any]:
        header = block["header"]
        h = header["height"]
        elected = self._pox_elected(h)
        tip, _ = self.pox._tip()  # noqa: SLF001
        prev = "" if h == 1 else tip
        bids = [
            {
                "consensus": "pox",
                "kind": "bid",
                "miner": miner,
                "btc_out": btc,
                "block_height": h,
            }
            for miner, btc in (("alice", 5), ("bob", 6), ("carol", 4))
        ]
        tenure = {
            "consensus": "pox",
            "kind": "tenure",
            "winner": elected,
            "prev": prev,
            "block_height": h,
        }
        return {"consensus": "pox", "messages": [*bids, tenure]}

    def authorize(self, block: Dict[str, Any], proof: Any) -> bool:
        if not isinstance(proof, dict) or proof.get("consensus") != "pox":
            return False
        header = block["header"]
        messages = proof.get("messages") or []
        bids = [m for m in messages if m.get("kind") == "bid"]
        tenures = [m for m in messages if m.get("kind") == "tenure"]
        for msg in bids:
            if not self.pox.is_valid(msg):
                return False
            self.pox.add_message(msg)
        elected = self.pox._elected_miner(header["height"])  # noqa: SLF001
        if elected is None or header["producer"] != elected:
            return False
        for msg in tenures:
            if not self.pox.is_valid(msg):
                return False
            self.pox.add_message(msg)
        self._chain_ids.append(block_id(header))
        return True

    def canonical(self) -> List[str]:
        return list(self._chain_ids)


class OuroborosDriver(_BaseDriver):
    def __init__(self, **_: Any) -> None:
        super().__init__()
        self.ouro = Ouroboros(_OURO_NONCE, _OURO_EPOCH, _ouro_table())
        self._chain_to_ouro: Dict[str, str] = {}

    def build_proof(self, block: Dict[str, Any]) -> Dict[str, Any]:
        header = block["header"]
        cid = block_id(header)
        slot = header["height"]
        parent = self._chain_to_ouro.get(header["parent"], "")
        leader = header["producer"]
        prior = list(self.ouro._order)  # noqa: SLF001
        obj = Ouroboros(_OURO_NONCE, _OURO_EPOCH, _ouro_table())
        for mid in prior:
            obj.add_message(self.ouro._blocks[mid])  # noqa: SLF001
        parent_record = obj._blocks.get(parent) if parent else None
        epoch, epoch_nonce = obj._epoch_nonce_for_slot(slot, parent_record)  # noqa: SLF001
        sk = _OURO_KEYS[leader]
        vrf_message = obj._vrf_message(epoch, epoch_nonce, slot, leader)  # noqa: SLF001
        proof, output, pk = vrf.evaluate(vrf_message, sk)
        return {
            "consensus": "ouroboros",
            "slot": slot,
            "parent": parent,
            "payload": cid,
            "leader": leader,
            "pk": pk.hex(),
            "proof": proof.hex(),
            "output": output.hex(),
        }

    def authorize(self, block: Dict[str, Any], proof: Any) -> bool:
        if not isinstance(proof, dict) or proof.get("consensus") != "ouroboros":
            return False
        cid = block_id(block["header"])
        if proof.get("payload") != cid:
            return False
        if not self.ouro.is_valid(proof):
            return False
        self.ouro.add_message(proof)
        digest = ouro_block_id(
            proof["slot"],
            proof["parent"],
            proof["payload"],
            proof["leader"],
            proof["pk"],
            proof["proof"],
            proof["output"],
        )
        self._chain_to_ouro[cid] = digest
        return True

    def canonical(self) -> List[str]:
        payloads: List[str] = []
        for digest in self.ouro.state()["canonical"]:
            payloads.append(self.ouro._blocks[digest]["payload"])  # noqa: SLF001
        return payloads