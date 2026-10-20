"""Live PeerJS id from the public broker. Not a golden vector."""

from chaincraft.channel import parse_address
from chaincraft.peer import fetch_peer_id, peer_options


def test_live_peerjs_id():
    ident = fetch_peer_id(timeout=20)
    parsed = parse_address(f"webrtc:{ident}")
    assert parsed["ok"] is True
    assert parsed["canonical"] == f"webrtc:{ident}"
    options = peer_options()
    assert options["host"] == "dechess-org-peerjs.vercel.app"
    assert options["port"] == 443
    assert options["path"] == "/"
    assert options["secure"] is True
    assert options["key"] == "peerjs"
