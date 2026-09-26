"""Localhost UDP link and payload caps — SPEC/features/channel-adapters.md."""

from chaincraft.adapters import (
    MAX_PIPE_BYTES,
    MAX_UDP_PAYLOAD,
    AdapterChannel,
    UdpLink,
    pipe_bus,
    udp_bus,
)


def test_localhost_datagram_round_trip():
    a = UdpLink()
    b = UdpLink()
    try:
        body = b"hello"
        a.send(b.host_port, body)
        source, got = b.recv()
        assert got == body
        assert source.startswith("127.0.0.1:")
    finally:
        a.close()
        b.close()


def test_udp_bus_rejects_oversize():
    bus = udp_bus()
    channel = AdapterChannel(bus)
    assert channel.listen("udp://127.0.0.1:1")
    assert channel.send("udp://127.0.0.1:1", "00" * MAX_UDP_PAYLOAD)
    assert channel.send("udp://127.0.0.1:1", "00" * (MAX_UDP_PAYLOAD + 1)) is False


def test_pipe_accepts_a_payload_the_loop_would_reject():
    bus = pipe_bus()
    channel = AdapterChannel(bus)
    assert channel.listen("pipe:alice")
    assert channel.send("pipe:alice", "00" * 65)
    assert channel.send("pipe:alice", "00" * MAX_PIPE_BYTES)
    assert channel.send("pipe:alice", "00" * (MAX_PIPE_BYTES + 1)) is False
    assert channel.send("pipe:alice", "loop-payload") is False
