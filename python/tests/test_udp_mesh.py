"""Two meshes exchange one envelope on the optional UDP listener."""

import time

from chaincraft.mesh import Mesh


def test_udp_listener_delivers_gossip():
    received = []
    left = Mesh()
    right = Mesh(on_app=lambda _type, data: received.append(data))
    left.start("127.0.0.1", 0)
    right.start("127.0.0.1", 0)
    try:
        right_udp = right.bind_udp()
        left.bind_udp()
        left.connect(f"udp://{right_udp}")
        left.broadcast("app.hello", {"message": "hi"})
        deadline = time.time() + 3
        while not received and time.time() < deadline:
            time.sleep(0.05)
        assert received == [{"message": "hi"}]
    finally:
        left.close()
        right.close()
