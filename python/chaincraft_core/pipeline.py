"""The apply pipeline — SPEC/semantics-v1.md section 3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .memento import StateMemento
from .object import SharedObject

__all__ = ["ApplyResult", "ObjectRegistry"]


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of pushing one message through the registry."""

    accepted: bool
    rejected_by: Optional[str] = None
    mementos: Dict[str, StateMemento] = field(default_factory=dict)

    @property
    def should_persist(self) -> bool:
        """Section 3 step 5 — persist and broadcast only on full success."""
        return self.accepted


class ObjectRegistry:
    """Objects in registration order, with the validate-all-then-apply pipeline.

    Registration order is load-bearing: it fixes the order in which mementos are
    threaded, so two nodes registering the same objects in different orders will
    compute different state.
    """

    def __init__(self) -> None:
        self._objects: List[Tuple[str, SharedObject]] = []

    def register(self, name: str, obj: SharedObject) -> "ObjectRegistry":
        if any(existing == name for existing, _ in self._objects):
            raise ValueError(f"object already registered: {name}")
        self._objects.append((name, obj))
        return self

    @property
    def names(self) -> List[str]:
        return [name for name, _ in self._objects]

    def get(self, name: str) -> SharedObject:
        for existing, obj in self._objects:
            if existing == name:
                return obj
        raise KeyError(name)

    def apply(self, message: Any) -> ApplyResult:
        """Validate against every object, then apply to each in order.

        Nothing mutates unless every object accepts, so a rejected message
        leaves the registry byte-identical to before the call.
        """
        for name, obj in self._objects:
            if not obj.is_valid(message):
                return ApplyResult(accepted=False, rejected_by=name)

        mementos: Dict[str, StateMemento] = {}
        threaded: Optional[StateMemento] = None
        for name, obj in self._objects:
            returned = obj.add_message(message, threaded)
            threaded = returned if returned is not None else obj.emit_state_memento()
            mementos[name] = threaded

        return ApplyResult(accepted=True, mementos=mementos)

    def state_digests(self) -> Dict[str, List[str]]:
        return {name: obj.get_state_digests() for name, obj in self._objects}
