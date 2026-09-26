"""In-process pipe mesh — SPEC/features/channel-adapters.md."""

import time

from chaincraft.adapters import AdapterChannel, pipe_bus


def test_pipe_mesh_throughput():
    peers_n = 4
    burst = 65536
    payload = "ab" * 64
    bus = pipe_bus()
    names = [f"pipe:n{index}" for index in range(peers_n)]
    peers = [AdapterChannel(bus) for _ in names]
    for peer, name in zip(peers, names):
        assert peer.listen(name)
    started = time.perf_counter()
    for index in range(burst):
        src = index % peers_n
        dst = (src + 1) % peers_n
        assert peers[src].send(names[dst], payload)
    elapsed = time.perf_counter() - started
    for peer in peers:
        got = peer.recv()
        assert len(got) == burst // peers_n
        assert got[0]["data"] == payload
        assert got[0]["from"].startswith("pipe:n")
    rate = burst / elapsed
    print(f"channel.pipe apply: {burst} events in {elapsed:.6f}s ({rate:.0f}/s)")
    assert elapsed < 30.0, elapsed
