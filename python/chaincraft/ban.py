"""Local peer strike list and inbound classification — discovery-ban.md."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from .discovery import is_valid_address

__all__ = [
    "BanSet",
    "DEFAULT_BAN_TTL_MS",
    "DEFAULT_STRIKE_LIMIT",
    "MAX_TRACKED",
    "classify_inbound",
]

DEFAULT_STRIKE_LIMIT = 3
DEFAULT_BAN_TTL_MS = 60_000
MAX_TRACKED = 64

_STRIKE_REASONS = frozenset({"digest_flood", "malformed"})
_VALID_REASONS = _STRIKE_REASONS | {"invalid_address"}


def classify_inbound(
    type_name: str,
    solicited: bool,
    duplicate: bool,
    address_ok: bool,
) -> Dict[str, Any]:
    if type_name == "ctl.peers" and not solicited:
        return {"action": "ignore", "reason": None}
    if type_name.startswith("ctl.") or type_name.startswith("link."):
        return {"action": "deliver", "reason": None}
    if not address_ok:
        return {"action": "drop", "reason": "invalid_address"}
    if duplicate:
        return {"action": "drop", "reason": "digest_flood"}
    return {"action": "deliver", "reason": None}


class _Entry:
    __slots__ = ("strikes", "banned_at")

    def __init__(self) -> None:
        self.strikes = 0
        self.banned_at: Optional[int] = None


class BanSet:
    """Process-local strike list; not gossiped or persisted."""

    __slots__ = ("strike_limit", "ban_ttl_ms", "_peers")

    def __init__(
        self,
        strike_limit: int = DEFAULT_STRIKE_LIMIT,
        ban_ttl_ms: int = DEFAULT_BAN_TTL_MS,
    ) -> None:
        if isinstance(strike_limit, bool) or not isinstance(strike_limit, int):
            raise ValueError("strike_limit must be a positive integer")
        if isinstance(ban_ttl_ms, bool) or not isinstance(ban_ttl_ms, int):
            raise ValueError("ban_ttl_ms must be a positive integer")
        if strike_limit < 1:
            raise ValueError("strike_limit must be a positive integer")
        if ban_ttl_ms < 1:
            raise ValueError("ban_ttl_ms must be a positive integer")
        self.strike_limit = strike_limit
        self.ban_ttl_ms = ban_ttl_ms
        self._peers: OrderedDict[str, _Entry] = OrderedDict()

    def _expire(self, peer: str, now_ms: int) -> None:
        entry = self._peers.get(peer)
        if entry is None or entry.banned_at is None:
            return
        if now_ms - entry.banned_at > self.ban_ttl_ms:
            del self._peers[peer]

    def _expire_all(self, now_ms: int) -> None:
        expired = [
            peer
            for peer, entry in self._peers.items()
            if entry.banned_at is not None and now_ms - entry.banned_at > self.ban_ttl_ms
        ]
        for peer in expired:
            del self._peers[peer]

    def _is_active_ban(self, entry: _Entry, now_ms: int) -> bool:
        if entry.banned_at is None:
            return False
        return now_ms - entry.banned_at <= self.ban_ttl_ms

    def _evict_if_needed(self) -> bool:
        if len(self._peers) < MAX_TRACKED:
            return True
        for peer, entry in self._peers.items():
            if entry.banned_at is None:
                del self._peers[peer]
                return True
        return False

    def _ensure_peer(self, peer: str) -> Optional[_Entry]:
        if peer in self._peers:
            return self._peers[peer]
        if not self._evict_if_needed():
            return None
        entry = _Entry()
        self._peers[peer] = entry
        return entry

    def note(self, peer: str, reason: str, now_ms: int) -> str:
        if (
            isinstance(now_ms, bool)
            or not isinstance(now_ms, int)
            or now_ms < 0
        ):
            return "ignored"
        if not is_valid_address(peer):
            return "ignored"
        if reason not in _VALID_REASONS:
            return "ignored"

        self._expire_all(now_ms)
        entry = self._peers.get(peer)
        if entry is not None and self._is_active_ban(entry, now_ms):
            return "banned"

        if reason == "invalid_address":
            entry = self._ensure_peer(peer)
            if entry is None:
                return "ignored"
            entry.strikes = self.strike_limit
            entry.banned_at = now_ms
            return "banned"

        entry = self._ensure_peer(peer)
        if entry is None:
            return "ignored"
        entry.strikes += 1
        if entry.strikes >= self.strike_limit:
            entry.banned_at = now_ms
            return "banned"
        return "strike"

    def is_banned(self, peer: str, now_ms: int) -> bool:
        self._expire(peer, now_ms)
        entry = self._peers.get(peer)
        if entry is None:
            return False
        return self._is_active_ban(entry, now_ms)

    def strikes(self, peer: str) -> int:
        entry = self._peers.get(peer)
        if entry is None:
            return 0
        return entry.strikes

    def banned(self, now_ms: int) -> List[str]:
        self._expire_all(now_ms)
        out = [
            peer
            for peer, entry in self._peers.items()
            if self._is_active_ban(entry, now_ms)
        ]
        return sorted(out)

    def state(self, now_ms: int) -> Dict[str, Any]:
        self._expire_all(now_ms)
        tracked = []
        for peer, entry in self._peers.items():
            tracked.append(
                {
                    "peer": peer,
                    "strikes": entry.strikes,
                    "banned_at": entry.banned_at,
                }
            )
        return {
            "tracked": tracked,
            "banned": self.banned(now_ms),
            "size": len(self._peers),
        }