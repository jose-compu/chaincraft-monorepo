"""Slush, Snowflake, and Snowball — SPEC/features/consensus-avalanche.md."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .memento import StateMemento
from .object import SharedObject, merkle_digest

__all__ = [
    "DEFAULT_ALPHA",
    "DEFAULT_BETA",
    "DEFAULT_K",
    "PHASES",
    "Avalanche",
]

PHASES = ("slush", "snowflake", "snowball")
COLORS = ("blue", "red")
DEFAULT_K = 2
DEFAULT_ALPHA = 2
DEFAULT_BETA = 2


class Avalanche(SharedObject):
    def __init__(
        self,
        phase: str = "snowball",
        k: int = DEFAULT_K,
        alpha: int = DEFAULT_ALPHA,
        beta: int = DEFAULT_BETA,
    ) -> None:
        if phase not in PHASES:
            raise ValueError("phase must be slush, snowflake, or snowball")
        if not (1 <= k <= 16):
            raise ValueError("k must be in 1..16")
        if not (1 <= alpha <= k) or not (alpha * 2 > k):
            raise ValueError("alpha must be in 1..k and greater than k/2")
        if not (1 <= beta <= 16):
            raise ValueError("beta must be in 1..16")
        self.phase = phase
        self.k = k
        self.alpha = alpha
        self.beta = beta
        self.pref = ""
        self.final = False
        self.cnt = 0
        self.rounds = 0
        self.d = {color: 0 for color in COLORS}

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def add_message(
        self, message: Any, frontier_state: Optional[StateMemento] = None
    ) -> Optional[StateMemento]:
        parsed = self._parse(message)
        if parsed is None:
            return self.emit_state_memento()
        kind = parsed[0]
        if kind == "init":
            self.pref = parsed[1]
        else:
            self._apply_round(parsed[1])
        return self.emit_state_memento()

    def emit_state_memento(self) -> StateMemento:
        return StateMemento.normalize(
            merkle_digest({"state": self.state(), "v": 1}),
            [],
        )

    def get_state_digests(self) -> List[str]:
        memo = self.emit_state_memento()
        return [memo.canonical_digest] if memo.canonical_digest else []

    def is_merkelized(self) -> bool:
        return True

    def state(self) -> Dict[str, Any]:
        return {
            "cnt": self.cnt,
            "d": {"blue": self.d["blue"], "red": self.d["red"]},
            "final": self.final,
            "phase": self.phase,
            "pref": self.pref,
            "rounds": self.rounds,
        }

    def _apply_round(self, winner: Optional[str]) -> None:
        self.rounds += 1
        if winner is None:
            if self.phase == "snowflake":
                self.cnt = 0
            return
        if self.phase == "slush":
            self.pref = winner
            return
        if self.phase == "snowflake":
            if self.pref == "" or self.pref == winner:
                self.pref = winner
                self.cnt += 1
            else:
                self.pref = winner
                self.cnt = 1
            if self.cnt >= self.beta:
                self.final = True
            return
        self.d[winner] += 1
        if (
            self.pref == ""
            or self.d[winner] > self.d[self.pref]
            or (self.d[winner] == self.d[self.pref] and winner < self.pref)
        ):
            self.pref = winner
        if self.d[self.pref] >= self.beta:
            self.final = True

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("consensus") != "avalanche":
            return None
        op = message.get("op")
        if op == "init":
            color = message.get("color")
            if color not in COLORS or self.pref:
                return None
            return ("init", color)
        if op != "round" or self.final:
            return None
        votes = message.get("votes")
        if not isinstance(votes, list) or len(votes) != self.k:
            return None
        counts = {color: 0 for color in COLORS}
        for vote in votes:
            if vote not in COLORS:
                return None
            counts[vote] += 1
        winner = None
        for color in COLORS:
            if counts[color] >= self.alpha:
                winner = color
        return ("round", winner)
