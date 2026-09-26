"""Apply and read throughput for app.stream — SPEC/features/app-stream.md."""

from __future__ import annotations

import time

from chaincraft.canonical import MAX_SAFE_INT
from chaincraft.stream import MAX_BATCH, Stream

BURST = 65536
KEEP = 32


def _apply(obj: Stream, message: dict) -> bool:
    if not obj.is_valid(message):
        return False
    obj.add_message(message)
    return True


def test_stream_apply_and_read_throughput():
    obj = Stream()
    assert _apply(
        obj, {"app": "stream", "broker": "n1", "op": "join", "stream": "orders"}
    )
    assert _apply(
        obj, {"app": "stream", "broker": "n2", "op": "join", "stream": "orders"}
    )
    for partition in (0, 1):
        assert _apply(
            obj,
            {
                "app": "stream",
                "op": "open",
                "partition": partition,
                "producer": "alice",
                "stream": "orders",
            },
        )
    assert _apply(
        obj, {"app": "stream", "keep": KEEP, "op": "retain", "stream": "orders"}
    )

    applied = 0
    started = time.perf_counter()
    for partition in (0, 1):
        seq = 0
        while seq < BURST // 2:
            records = []
            for _ in range(MAX_BATCH):
                records.append({"payload": "x", "producer": "alice", "seq": seq})
                seq += 1
            assert _apply(
                obj,
                {
                    "app": "stream",
                    "op": "append",
                    "partition": partition,
                    "records": records,
                    "stream": "orders",
                },
            )
            applied += MAX_BATCH
    elapsed = time.perf_counter() - started
    rate = applied / elapsed if elapsed else applied
    print(
        f"app.stream apply: {applied} events in {elapsed:.6f}s ({rate:.0f}/s)",
        flush=True,
    )
    assert elapsed < 30.0, elapsed

    assert _apply(
        obj, {"app": "stream", "broker": "n2", "op": "fail", "stream": "orders"}
    )
    head = obj.read("orders", 0, None, KEEP)
    assert len(head) == KEEP
    assert head[-1]["seq"] == BURST // 2 - 1
    assert _apply(
        obj, {"app": "stream", "broker": "n1", "op": "fail", "stream": "orders"}
    )
    assert obj.read("orders", 0, None, 4) == []
    assert obj.state()["streams"][0]["partitions"][0]["events"]

    read_started = time.perf_counter()
    reads = 200
    assert _apply(
        obj, {"app": "stream", "broker": "n1", "op": "join", "stream": "orders"}
    )
    for _ in range(reads):
        assert len(obj.read("orders", 1, None, KEEP)) == KEEP
    read_elapsed = time.perf_counter() - read_started
    read_rate = reads / read_elapsed if read_elapsed else reads
    print(
        f"app.stream read: {reads} reads in {read_elapsed:.6f}s ({read_rate:.0f}/s)",
        flush=True,
    )

    sparse = Stream()
    assert _apply(
        sparse, {"app": "stream", "op": "open", "producer": "alice", "stream": "orders"}
    )
    assert _apply(
        sparse,
        {
            "app": "stream",
            "op": "produce",
            "payload": "z",
            "producer": "alice",
            "seq": MAX_SAFE_INT,
            "stream": "orders",
        },
    )
    reject_started = time.perf_counter()
    assert (
        sparse.is_valid(
            {
                "app": "stream",
                "group": "workers",
                "op": "commit",
                "producer": "alice",
                "seq": MAX_SAFE_INT,
                "stream": "orders",
            }
        )
        is False
    )
    reject_elapsed = time.perf_counter() - reject_started
    print(f"app.stream high-seq commit rejection: {reject_elapsed:.6f}s", flush=True)
    assert reject_elapsed < 1.0, reject_elapsed
