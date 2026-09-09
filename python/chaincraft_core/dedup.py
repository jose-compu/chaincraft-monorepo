"""Deduplication and relay — SPEC/wire-v1.md section 7."""

from __future__ import annotations

from typing import Dict

from .envelope import Envelope

DEFAULT_CAPACITY = 100000


class SeenDigests:
    """Bounded set of seen payload digests, evicting the oldest insertion first.

    Backed by a dict because it is insertion-ordered and leaves that order
    undisturbed when a key is re-added, which is the no-refresh rule in 7.2.
    """

    __slots__ = ("_digests", "capacity")

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self._digests: Dict[str, None] = {}

    def __contains__(self, digest: object) -> bool:
        return digest in self._digests

    def __len__(self) -> int:
        return len(self._digests)

    def add(self, digest: str) -> bool:
        """Record a digest. Returns False when it was already present."""
        if digest in self._digests:
            return False
        if len(self._digests) >= self.capacity:
            oldest = next(iter(self._digests))
            del self._digests[oldest]
        self._digests[digest] = None
        return True

    def clear(self) -> None:
        self._digests.clear()


class Deduplicator:
    """The receive-path gate.

    ``should_process`` has the side effect of recording the digest, so a caller
    asks once per received envelope and acts on the answer. ``should_relay``
    assumes the caller only relays what ``should_process`` accepted.
    """

    __slots__ = ("seen",)

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self.seen = SeenDigests(capacity)

    def should_process(self, envelope: Envelope) -> bool:
        # Control messages are point-to-point, so the same ctl.hello arriving on
        # two connections must be handled twice, not dropped as a repeat.
        if envelope.is_control():
            return True
        return self.seen.add(envelope.id)

    def should_relay(self, envelope: Envelope) -> bool:
        return not envelope.is_control()
