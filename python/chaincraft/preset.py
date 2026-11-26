"""Node preset — SPEC/features/node-preset.md."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Dict, List, Mapping, Optional, Set

from .chain import TransferChain
from .chain_driver import make_driver
from .crdt import CrdtKv
from .ledger_balance import BalanceLedger
from .ledger_utxo import UtxoLedger
from .mesh import Mesh, parse_listen
from .pubsub import PubSub

__all__ = ["start"]

_CONSENSUS = {
    "pow",
    "poa",
    "pos",
    "pbft",
    "poet",
    "avalanche",
    "beacon",
    "pox",
    "ouroboros",
}
_PROTOCOLS = {"transfer", "balance", "utxo", "crdt", "pubsub"} | _CONSENSUS


def _reject_unknown(config: Mapping[str, Any], allowed: Set[str]) -> None:
    for key in config:
        if key not in allowed:
            raise ValueError(f"unknown config key: {key}")


def start(config: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    protocol = config.get("protocol")
    if not isinstance(protocol, str) or protocol not in _PROTOCOLS:
        raise ValueError("invalid protocol")
    listen = config.get("listen", "127.0.0.1:0")
    peers = config.get("peers", [])
    udp = config.get("udp", False)
    if protocol == "transfer":
        _reject_unknown(
            config,
            {
                "protocol",
                "consensus",
                "genesis",
                "reward",
                "authorities",
                "listen",
                "peers",
                "udp",
            },
        )
        consensus = config.get("consensus")
        if not isinstance(consensus, str):
            raise ValueError("consensus required for transfer")
        genesis = config.get("genesis")
        if not isinstance(genesis, dict):
            raise ValueError("genesis required")
        reward = config.get("reward", 0)
        opts: Dict[str, Any] = {}
        if consensus == "poa":
            authorities = config.get("authorities")
            if not isinstance(authorities, list) or not authorities:
                raise ValueError("authorities required for poa")
            opts["authorities"] = authorities
        driver = make_driver(consensus, **opts)
        chain = TransferChain(genesis, reward=reward, driver=driver)
        mesh = _mesh_for(chain, protocol, listen, peers, udp)
        return _transfer_handle(mesh, chain)
    if protocol == "balance":
        _reject_unknown(config, {"protocol", "genesis", "listen", "peers", "udp"})
        genesis = config.get("genesis", {"alice": 100})
        obj = BalanceLedger(genesis)
        mesh = _mesh_for(obj, protocol, listen, peers, udp)
        return _object_handle(mesh, obj, protocol)
    if protocol == "utxo":
        _reject_unknown(config, {"protocol", "genesis", "listen", "peers", "udp"})
        genesis = config.get("genesis", {"alice": 100})
        obj = UtxoLedger(genesis)
        mesh = _mesh_for(obj, protocol, listen, peers, udp)
        return _object_handle(mesh, obj, protocol)
    if protocol == "crdt":
        _reject_unknown(config, {"protocol", "listen", "peers", "udp"})
        obj = CrdtKv()
        mesh = _mesh_for(obj, protocol, listen, peers, udp)
        return _object_handle(mesh, obj, protocol)
    if protocol == "pubsub":
        _reject_unknown(config, {"protocol", "listen", "peers", "udp"})
        obj = PubSub()
        mesh = _mesh_for(obj, protocol, listen, peers, udp)
        return _object_handle(mesh, obj, protocol)
  # consensus-only presets attach the consensus object
    _reject_unknown(config, {"protocol", "listen", "peers", "udp"})
    obj = _consensus_object(protocol, config)
    mesh = _mesh_for(obj, protocol, listen, peers, udp)
    return _object_handle(mesh, obj, protocol)


def _consensus_object(protocol: str, config: Mapping[str, Any]) -> Any:
    if protocol == "poa":
        from .consensus_poa import ProofOfAuthority

        authorities = config.get("authorities", ["alice"])
        return ProofOfAuthority(authorities)
    if protocol == "pow":
        from .consensus_pow import ProofOfWork

        return ProofOfWork(config.get("difficulty", 2))
    if protocol == "pos":
        from .consensus_pos import ProofOfStake

        return ProofOfStake()
    if protocol == "pbft":
        from .consensus_pbft import PBFT

        return PBFT(config.get("replicas"))
    if protocol == "poet":
        from .consensus_poet import ProofOfElapsedTime

        return ProofOfElapsedTime(config.get("seed", "chaincraft-poet-genesis"))
    if protocol == "avalanche":
        from .consensus_avalanche import Avalanche

        return Avalanche()
    if protocol == "beacon":
        from .consensus_beacon import RandomnessBeacon

        return RandomnessBeacon()
    if protocol == "pox":
        from .consensus_pox import ProofOfTransfer

        return ProofOfTransfer(
            config.get("seed", "0" * 64),
            config.get("cycle_length", 3),
            config.get("stackers", [("alice", 100)]),
        )
    if protocol == "ouroboros":
        from .chain_driver import _ouro_table, _OURO_EPOCH, _OURO_NONCE
        from .consensus_ouroboros import Ouroboros

        return Ouroboros(_OURO_NONCE, _OURO_EPOCH, _ouro_table())
    raise ValueError("invalid protocol")


def _mesh_for(
    obj: Any,
    protocol: str,
    listen: str,
    peers: Any,
    udp: bool,
) -> Mesh:
    lock = threading.Lock()

    def on_app(app_type: str, data: Any) -> None:
        if app_type != f"app.{protocol}":
            return
        with lock:
            if protocol == "transfer":
                if isinstance(data, dict) and data.get("chain") == "transfer":
                    obj.accept_block(data)
                elif isinstance(data, dict) and "signature" in data:
                    obj.submit(data)
            elif hasattr(obj, "is_valid") and obj.is_valid(data):
                obj.add_message(data)

    mesh = Mesh(on_app=on_app)
    host, port = parse_listen(listen if isinstance(listen, str) else None)
    mesh.start(host, port)
    if udp:
        mesh.bind_udp()
    if isinstance(peers, list):
        for addr in peers:
            if isinstance(addr, str) and addr:
                mesh.connect(addr)
    return mesh


def _object_handle(mesh: Mesh, obj: Any, protocol: str) -> Dict[str, Any]:
    app = f"app.{protocol}"

    def state() -> Any:
        return obj.state()

    def submit(message: Any) -> bool:
        if hasattr(obj, "is_valid"):
            if not obj.is_valid(message):
                return False
            obj.add_message(message)
            mesh.broadcast(app, message)
            return True
        return False

    def connect(addr: str) -> None:
        mesh.connect(addr)

    def close() -> None:
        mesh.close()

    return {
        "listen_addr": mesh.listen_addr,
        "state": state,
        "submit": submit,
        "connect": connect,
        "close": close,
    }


def _transfer_handle(mesh: Mesh, chain: TransferChain) -> Dict[str, Any]:
    base = _object_handle(mesh, chain, "transfer")

    def submit(message: Any) -> bool:
        if isinstance(message, dict) and message.get("chain") == "transfer":
            if chain.accept_block(message):
                mesh.broadcast("app.transfer", message)
                return True
            return False
        if chain.submit(message):
            mesh.broadcast("app.transfer", message)
            return True
        return False

    def produce(time: int, producer: Optional[str] = None) -> Any:
        prod = producer or "alice"
        block = chain.produce(time, prod)
        if block is not None:
            mesh.broadcast("app.transfer", block)
        return block

    base["submit"] = submit
    base["produce"] = produce
    return base


def start_json(text: str) -> Dict[str, Any]:
    config = json.loads(text)
    return start(config)