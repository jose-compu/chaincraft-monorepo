"""Control messages — SPEC/wire-v1.md section 5."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .envelope import PROTOCOL_VERSION, Envelope, ProtocolError

__all__ = [
    "HELLO",
    "PEERS_REQUEST",
    "PEERS",
    "DIGEST_REQUEST",
    "DIGEST",
    "MESSAGES_REQUEST",
    "MESSAGES",
    "CONTROL_TYPES",
    "CAPABILITIES",
    "hello",
    "peers_request",
    "peers",
    "digest_request",
    "digest",
    "messages_request",
    "messages",
    "parse_hello",
]

HELLO = "ctl.hello"
PEERS_REQUEST = "ctl.peers.request"
PEERS = "ctl.peers"
DIGEST_REQUEST = "ctl.digest.request"
DIGEST = "ctl.digest"
MESSAGES_REQUEST = "ctl.messages.request"
MESSAGES = "ctl.messages"

CONTROL_TYPES = frozenset(
    {HELLO, PEERS_REQUEST, PEERS, DIGEST_REQUEST, DIGEST, MESSAGES_REQUEST, MESSAGES}
)

CAP_GOSSIP = "gossip"
CAP_DIGEST_SYNC = "digest-sync"
CAP_UDP = "udp"
CAPABILITIES = frozenset({CAP_GOSSIP, CAP_DIGEST_SYNC, CAP_UDP})


def hello(
    impl: str,
    caps: Sequence[str] = (CAP_GOSSIP, CAP_DIGEST_SYNC),
    listen: Optional[str] = None,
    *,
    ts: Optional[int] = None,
) -> Envelope:
    data: Dict[str, Any] = {
        "v": PROTOCOL_VERSION,
        "impl": impl,
        "caps": sorted(caps),
    }
    if listen is not None:
        data["listen"] = listen
    return Envelope.build(HELLO, data, ts=ts)


def parse_hello(env: Envelope) -> Dict[str, Any]:
    """Validate a ctl.hello payload and return it.

    Raises ProtocolError when the peer speaks a version we cannot serve, so the
    caller can disconnect cleanly instead of failing later in an obscure way.
    """
    if env.type != HELLO:
        raise ProtocolError(f"expected {HELLO}, got {env.type}")
    data = env.data
    if not isinstance(data, dict):
        raise ProtocolError("ctl.hello data must be an object")

    version = data.get("v")
    if version is True or version is False or not isinstance(version, int):
        raise ProtocolError("ctl.hello requires an integer v")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"peer speaks protocol v{version}, we speak v{PROTOCOL_VERSION}")

    impl = data.get("impl")
    if not isinstance(impl, str) or not impl:
        raise ProtocolError("ctl.hello requires impl")

    caps = data.get("caps")
    if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
        raise ProtocolError("ctl.hello requires caps as an array of strings")

    listen = data.get("listen")
    if listen is not None and not isinstance(listen, str):
        raise ProtocolError("ctl.hello listen must be a string")

    # Unknown capabilities are ignored, not rejected — that is how we stay
    # forward compatible with peers newer than us.
    return {
        "v": version,
        "impl": impl,
        "caps": [c for c in caps if c in CAPABILITIES],
        "unknown_caps": [c for c in caps if c not in CAPABILITIES],
        "listen": listen,
    }


def peers_request(*, ts: Optional[int] = None) -> Envelope:
    return Envelope.build(PEERS_REQUEST, {}, ts=ts)


def peers(addresses: Sequence[str], *, ts: Optional[int] = None) -> Envelope:
    return Envelope.build(PEERS, {"peers": list(addresses)}, ts=ts)


def digest_request(object_name: str, *, ts: Optional[int] = None) -> Envelope:
    return Envelope.build(DIGEST_REQUEST, {"object": object_name}, ts=ts)


def digest(
    object_name: str,
    digest_hex: str,
    frontier: Sequence[str] = (),
    *,
    ts: Optional[int] = None,
) -> Envelope:
    return Envelope.build(
        DIGEST,
        {"object": object_name, "digest": digest_hex, "frontier": list(frontier)},
        ts=ts,
    )


def messages_request(
    object_name: str, since: str, *, ts: Optional[int] = None
) -> Envelope:
    return Envelope.build(
        MESSAGES_REQUEST, {"object": object_name, "since": since}, ts=ts
    )


def messages(
    object_name: str, envelopes: Sequence[Envelope], *, ts: Optional[int] = None
) -> Envelope:
    return Envelope.build(
        MESSAGES,
        {"object": object_name, "messages": [e.to_dict() for e in envelopes]},
        ts=ts,
    )
