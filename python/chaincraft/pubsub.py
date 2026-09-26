"""Topic publish-subscribe — SPEC/features/app-pubsub.md."""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple

from .canonical import MAX_SAFE_INT
from .object import SharedObject

__all__ = ["MAX_MEMBERS", "MAX_POSTS", "MAX_ROOMS", "MAX_TEXT", "PubSub"]

MAX_ROOMS = 32
MAX_MEMBERS = 32
MAX_POSTS = 64
MAX_TEXT = 1024

_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def _name(value: Any) -> bool:
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


class _Room:
    def __init__(self) -> None:
        self.members: set[str] = set()
        self.posts: Dict[Tuple[str, int], str] = {}


class PubSub(SharedObject):
    def __init__(self) -> None:
        self._rooms: Dict[str, _Room] = {}

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def receive(self, message: Any) -> None:
        parsed = self._parse(message)
        if parsed is None:
            return
        op, room_name, author, text, seq = parsed
        if op == "subscribe":
            room = self._rooms.setdefault(room_name, _Room())
            room.members.add(author)
        elif op == "unsubscribe":
            room = self._rooms[room_name]
            room.members.discard(author)
            if not room.members and not room.posts:
                del self._rooms[room_name]
        else:
            self._rooms[room_name].posts[(author, seq)] = text

    def state(self) -> Dict[str, Any]:
        return {"rooms": self._room_list()}

    def _room_list(self) -> list:
        rooms = []
        for name in sorted(self._rooms):
            room = self._rooms[name]
            posts = [
                {"author": author, "seq": seq, "text": text}
                for (author, seq), text in room.posts.items()
            ]
            posts.sort(key=lambda post: (post["seq"], post["author"]))
            rooms.append(
                {
                    "name": name,
                    "members": sorted(room.members),
                    "posts": posts,
                }
            )
        return rooms

    def _parse(self, message: Any):
        if not isinstance(message, dict) or message.get("app") != "pubsub":
            return None
        op = message.get("op")
        room = message.get("room")
        author = message.get("author")
        if op not in ("subscribe", "unsubscribe", "publish"):
            return None
        if not _name(room) or not _name(author):
            return None
        if op == "subscribe":
            existing = self._rooms.get(room)
            if existing is None and len(self._rooms) >= MAX_ROOMS:
                return None
            if existing is not None and author not in existing.members:
                if len(existing.members) >= MAX_MEMBERS:
                    return None
            return ("subscribe", room, author, None, None)
        if op == "unsubscribe":
            existing = self._rooms.get(room)
            if existing is None or author not in existing.members:
                return None
            return ("unsubscribe", room, author, None, None)
        text = message.get("text")
        seq = message.get("seq")
        if not isinstance(text, str) or not (1 <= len(text) <= MAX_TEXT):
            return None
        if not _is_int(seq) or not (0 <= seq <= MAX_SAFE_INT):
            return None
        existing = self._rooms.get(room)
        if existing is None or author not in existing.members:
            return None
        if (author, seq) in existing.posts or len(existing.posts) >= MAX_POSTS:
            return None
        return ("publish", room, author, text, seq)
