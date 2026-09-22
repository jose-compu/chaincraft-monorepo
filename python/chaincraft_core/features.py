"""Feature manifest — the IDs this implementation claims to provide.

Cross-checked against SPEC/features.yaml by tools/parity_check.py. A registry
entry claiming a feature absent from this list is a hard CI failure, which is
what keeps the registry from drifting into fiction.

Add an ID here only when the feature is implemented and its vectors pass.

    python -m chaincraft_core.features
"""

from __future__ import annotations

import json
import sys

__all__ = ["FEATURES", "main"]

FEATURES = frozenset(
    {
        # Level 0 — wire protocol
        "wire.canonical-json",
        "wire.payload-digest",
        "wire.envelope",
        "wire.framing-tcp",
        "wire.framing-udp",
        "wire.control",
        "wire.version-negotiation",
        "wire.sig-schnorr",
        "wire.sig-ed25519",
        "wire.dedup",
        # Level 1 — object semantics
        "object.contract",
        "object.pipeline",
        "object.memento",
        "object.merkle-digest",
        "object.tiebreak",
        # Level 2 — crypto
        "crypto.ecdsa",
        "crypto.vdf",
        "crypto.vrf",
        "discovery.peer",
        "discovery.local",
        "consensus.pow",
        "consensus.pos",
        "consensus.pbft",
        "ledger.balance",
        "ledger.utxo",
        "mempool.basic",
        "fees.policy",
        "storage.persistent",
        "cli.node",
        "bittorrent.swarm",
        "wire.channel",
    }
)


def main() -> int:
    from . import IMPL, WIRE_VERSION, __version__

    json.dump(
        {
            "impl": IMPL,
            "language": "python",
            "version": __version__,
            "wire_version": WIRE_VERSION,
            "features": sorted(FEATURES),
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
