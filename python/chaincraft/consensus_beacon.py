"""Chained VRF randomness beacon — SPEC/features/consensus-beacon.md."""

from __future__ import annotations

from typing import Any

from . import vrf
from .canonical import MAX_SAFE_INT, canonical_json
from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = ["RandomnessBeacon", "pulse_id"]

GENESIS_PREVIOUS = "0" * 64


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def _hex_lower(text: Any, nbytes: int) -> str | None:
    if not isinstance(text, str) or len(text) != nbytes * 2:
        return None
    if text != text.lower():
        return None
    try:
        bytes.fromhex(text)
    except ValueError:
        return None
    return text


def pulse_id(height: int, output: str, pk: str, previous: str, proof: str) -> str:
    return merkle_digest(
        {
            "height": height,
            "output": output,
            "pk": pk,
            "previous": previous,
            "proof": proof,
        }
    )


class RandomnessBeacon(SharedObject):
    def __init__(self) -> None:
        self._order: list[str] = []
        self._pulses: dict[str, dict[str, Any]] = {}

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def add_message(
        self, message: Any, frontier_state: StateMemento | None = None
    ) -> StateMemento | None:
        parsed = self._parse(message)
        if parsed is None:
            return self.emit_state_memento()
        digest, record = parsed
        self._pulses[digest] = record
        self._order.append(digest)
        return self.emit_state_memento()

    def emit_state_memento(self) -> StateMemento:
        height, output = self._tip()
        return StateMemento.normalize(
            merkle_digest({"height": height, "output": output, "v": 1}),
            [],
        )

    def get_state_digests(self) -> list[str]:
        if not self._order:
            return []
        return [self._order[-1]]

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> dict[str, Any]:
        height, output = self._tip()
        pulses = list(self._order)
        return {
            "canonical": pulses,
            "height": height,
            "output": output,
            "pulses": pulses,
        }

    def _tip(self) -> tuple[int, str]:
        if not self._order:
            return -1, ""
        record = self._pulses[self._order[-1]]
        return record["height"], record["output"]

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("consensus") != "beacon":
            return None
        height = message.get("height")
        if not _is_int(height) or height < 0 or height > MAX_SAFE_INT:
            return None
        previous = _hex_lower(message.get("previous"), 32)
        pk = _hex_lower(message.get("pk"), 33)
        proof = _hex_lower(message.get("proof"), 64)
        output_hex = _hex_lower(message.get("output"), 32)
        if previous is None or pk is None or proof is None or output_hex is None:
            return None
        tip_height, tip_output = self._tip()
        if tip_height < 0:
            if height != 0 or previous != GENESIS_PREVIOUS:
                return None
        elif height != tip_height + 1 or previous != tip_output:
            return None
        vrf_message = canonical_json({"height": height, "previous": previous}).encode(
            "utf-8"
        )
        if not vrf.verify(
            vrf_message,
            bytes.fromhex(proof),
            bytes.fromhex(pk),
            bytes.fromhex(output_hex),
        ):
            return None
        digest = pulse_id(height, output_hex, pk, previous, proof)
        if digest in self._pulses:
            return None
        return digest, {"height": height, "output": output_hex}
