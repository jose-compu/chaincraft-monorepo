"""Level 1 unit tests — one test per normative rule in SPEC/semantics-v1.md."""

from __future__ import annotations

from typing import Any, List, Optional

import pytest
from conformance_objects import Counter, Mirror, build_registry

from chaincraft import (
    ObjectRegistry,
    SharedObject,
    StateMemento,
    canonical_json,
    frontier_digest,
    merkle_digest,
    payload_digest,
    wins_replacement,
)

D1 = "1" * 64
D2 = "2" * 64
D3 = "3" * 64


# --- section 2: the object contract -----------------------------------------


class TestContract:
    def test_a_prototype_only_implements_receive(self):
        seen = []

        class Room(SharedObject):
            def receive(self, message: Any) -> None:
                seen.append(message["text"])

        room = Room()
        assert room.is_valid({"text": "hi"}) is True
        assert room.add_message({"text": "hi"}) is None
        assert seen == ["hi"]
        assert room.is_merkelized() is False
        assert room.get_state_digests() == []
        assert room.emit_state_memento() == StateMemento.normalize()

        registry = ObjectRegistry()
        registry.register("room", Room())
        result = registry.apply({"text": "hello"})
        assert result.accepted is True
        assert result.mementos["room"] == StateMemento.normalize()

    def test_defaults_are_the_non_merkelized_case(self):
        obj = SharedObject()
        assert obj.is_valid({"text": "hi"}) is True
        assert obj.add_message({"text": "hi"}) is None
        assert obj.is_merkelized() is False
        assert obj.get_state_digests() == []
        assert obj.emit_state_memento() == StateMemento.normalize()

    def test_is_valid_is_side_effect_free(self):
        counter = Counter()
        for _ in range(5):
            assert counter.is_valid({"delta": 1, "seq": 1}) is True
        assert counter.state() == {"seq": 0, "total": 0, "head": ""}


# --- section 3: the apply pipeline ------------------------------------------


class TestPipeline:
    def test_accepted_message_applies_to_every_object(self):
        registry = build_registry()
        result = registry.apply({"delta": 5, "seq": 1})
        assert result.accepted
        assert result.rejected_by is None
        assert registry.get("counter").state()["total"] == 5
        assert registry.get("mirror").state()["count"] == 1

    def test_rejection_names_the_rejecting_object(self):
        registry = build_registry()
        result = registry.apply({"delta": 1, "seq": 99})
        assert not result.accepted
        assert result.rejected_by == "counter"

    def test_rejection_is_all_or_nothing(self):
        """A message valid for counter but invalid for mirror mutates neither."""
        registry = build_registry()
        registry.apply({"delta": 5, "seq": 1})
        before = (registry.get("counter").state(), registry.get("mirror").state())

        result = registry.apply({"delta": 5, "seq": 2, "reject_mirror": True})
        assert not result.accepted
        assert result.rejected_by == "mirror"

        after = (registry.get("counter").state(), registry.get("mirror").state())
        assert after == before, "counter must not have applied the message"

    def test_memento_threads_in_registration_order(self):
        registry = build_registry()
        registry.apply({"delta": 1, "seq": 1})
        counter_head = registry.get("counter").state()["head"]
        assert registry.get("mirror").state()["last_frontier"] == [counter_head]

    def test_emit_state_memento_used_when_add_message_returns_nothing(self):
        registry = build_registry()
        result = registry.apply({"delta": 1, "seq": 1})
        mirror_memento = result.mementos["mirror"]
        assert mirror_memento == registry.get("mirror").emit_state_memento()

    def test_first_object_receives_no_frontier_state(self):
        seen: List[Optional[StateMemento]] = []

        class Recorder(SharedObject):
            def is_valid(self, message: Any) -> bool:
                return True

            def add_message(self, message, frontier_state=None):
                seen.append(frontier_state)
                return None

            def emit_state_memento(self) -> StateMemento:
                return StateMemento.normalize(D1)

        registry = ObjectRegistry()
        registry.register("first", Recorder()).register("second", Recorder())
        registry.apply({"any": "thing"})
        assert seen[0] is None
        assert seen[1] == StateMemento.normalize(D1)

    def test_no_object_mutates_before_all_have_validated(self):
        order: List[str] = []

        class Tracer(SharedObject):
            def __init__(self, name: str, valid: bool) -> None:
                self.name = name
                self.valid = valid

            def is_valid(self, message: Any) -> bool:
                order.append(f"valid:{self.name}")
                return self.valid

            def add_message(self, message, frontier_state=None):
                order.append(f"apply:{self.name}")
                return None

            def emit_state_memento(self) -> StateMemento:
                return StateMemento.normalize()

        registry = ObjectRegistry()
        registry.register("a", Tracer("a", True)).register("b", Tracer("b", True))
        registry.apply({})
        assert order == ["valid:a", "valid:b", "apply:a", "apply:b"]

    def test_should_persist_tracks_acceptance(self):
        registry = build_registry()
        assert registry.apply({"delta": 1, "seq": 1}).should_persist is True
        assert registry.apply({"delta": 1, "seq": 99}).should_persist is False

    def test_duplicate_registration_rejected(self):
        registry = ObjectRegistry()
        registry.register("counter", Counter())
        with pytest.raises(ValueError, match="already registered"):
            registry.register("counter", Counter())

    def test_registration_order_is_preserved(self):
        registry = ObjectRegistry()
        registry.register("z", Counter()).register("a", Mirror())
        assert registry.names == ["z", "a"]


# --- section 4: StateMemento ------------------------------------------------


class TestMemento:
    def test_canonical_digest_joins_the_frontier(self):
        memento = StateMemento.normalize(D1, [])
        assert memento.frontier_digests == [D1]

    def test_frontier_is_sorted(self):
        memento = StateMemento.normalize("", [D3, D1, D2])
        assert memento.frontier_digests == [D1, D2, D3]

    def test_frontier_is_deduplicated(self):
        memento = StateMemento.normalize(D1, [D1, D1, D2])
        assert memento.frontier_digests == [D1, D2]

    def test_empty_entries_dropped(self):
        memento = StateMemento.normalize("", ["", D1, ""])
        assert memento.frontier_digests == [D1]

    def test_empty_canonical_digest_not_appended(self):
        memento = StateMemento.normalize("", [D1])
        assert memento.frontier_digests == [D1]
        assert memento.canonical_digest == ""

    def test_revision_and_metadata_reset(self):
        memento = StateMemento.normalize(D1, [D2])
        assert memento.revision == 0
        assert memento.metadata == {}

    def test_normalize_with_no_arguments(self):
        memento = StateMemento.normalize()
        assert memento.canonical_digest == ""
        assert memento.frontier_digests == []

    def test_normalization_is_route_independent(self):
        """Two nodes reaching the same heads by different routes agree."""
        a = StateMemento.normalize(D1, [D2, D3])
        b = StateMemento.normalize(D1, [D3, D2, D2])
        assert a.frontier_digests == b.frontier_digests


class TestReorgDetection:
    def test_no_previous_is_not_a_reorg(self):
        assert StateMemento.normalize(D1).indicates_reorg_against(None) is False

    def test_same_head_is_not_a_reorg(self):
        current = StateMemento.normalize(D1)
        assert current.indicates_reorg_against(StateMemento.normalize(D1)) is False

    def test_building_on_previous_head_is_not_a_reorg(self):
        previous = StateMemento.normalize(D1)
        current = StateMemento.normalize(D2, [D1])
        assert current.indicates_reorg_against(previous) is False

    def test_branch_not_containing_previous_head_is_a_reorg(self):
        previous = StateMemento.normalize(D1)
        current = StateMemento.normalize(D2, [D3])
        assert current.indicates_reorg_against(previous) is True

    def test_empty_canonical_digest_is_not_a_reorg(self):
        assert (
            StateMemento.normalize("", [D2]).indicates_reorg_against(
                StateMemento.normalize(D1)
            )
            is False
        )
        assert (
            StateMemento.normalize(D2).indicates_reorg_against(
                StateMemento.normalize("", [D1])
            )
            is False
        )


# --- section 5: merkelized digests ------------------------------------------


class TestMerkleDigest:
    def test_digest_is_64_lowercase_hex(self):
        digest = merkle_digest({"seq": 1, "v": 1})
        assert len(digest) == 64
        assert digest == digest.lower()

    def test_shares_canonicalization_with_the_wire_payload_digest(self):
        """One canonicalization for both, or state and wire hashes diverge."""
        payload = {"seq": 1, "total": 5, "v": 1}
        assert merkle_digest(payload) == payload_digest(payload)

    def test_key_order_does_not_change_the_digest(self):
        assert merkle_digest({"a": 1, "b": 2}) == merkle_digest({"b": 2, "a": 1})

    def test_previous_digest_links_a_chain(self):
        first = merkle_digest({"previous_digest": "", "seq": 1, "total": 1, "v": 1})
        second = merkle_digest({"previous_digest": first, "seq": 2, "total": 2, "v": 1})
        assert first != second

    def test_parents_link_a_dag(self):
        one = merkle_digest({"parents": [D1, D2], "v": 1})
        two = merkle_digest({"parents": [D2, D1], "v": 1})
        assert one != two, "parent order is significant inside a payload"


class TestFrontierDigest:
    def test_head_order_does_not_matter(self):
        assert frontier_digest([D2, D1]) == frontier_digest([D1, D2])

    def test_empty_heads_dropped(self):
        assert frontier_digest(["", D1]) == frontier_digest([D1])

    def test_format_is_pinned(self):
        expected = payload_digest({"frontier_heads": [D1, D2], "v": 1})
        assert frontier_digest([D2, D1]) == expected

    def test_empty_frontier_has_a_digest(self):
        assert frontier_digest([]) == payload_digest({"frontier_heads": [], "v": 1})


# --- section 6: replacement and tie-breaking --------------------------------


class TestReplacement:
    def test_higher_rank_wins(self):
        assert wins_replacement(2, D3, 1, D1) is True

    def test_lower_rank_loses(self):
        assert wins_replacement(1, D1, 2, D3) is False

    def test_tie_broken_by_lowest_digest(self):
        assert wins_replacement(1, D1, 1, D2) is True
        assert wins_replacement(1, D2, 1, D1) is False

    def test_identical_entry_does_not_replace_itself(self):
        """Gossip redelivers messages; self-replacement would mutate state."""
        assert wins_replacement(1, D1, 1, D1) is False

    def test_tie_break_is_deterministic_across_argument_order(self):
        """Exactly one of two tied entries wins, whichever side asks."""
        assert wins_replacement(1, D1, 1, D2) != wins_replacement(1, D2, 1, D1)


# --- section 8: conformance objects -----------------------------------------


class TestConformanceObjects:
    def test_counter_requires_consecutive_sequence(self):
        counter = Counter()
        assert counter.is_valid({"delta": 1, "seq": 1}) is True
        assert counter.is_valid({"delta": 1, "seq": 2}) is False
        assert counter.is_valid({"delta": 1, "seq": 0}) is False

    def test_counter_bounds_delta(self):
        counter = Counter()
        assert counter.is_valid({"delta": 100, "seq": 1}) is True
        assert counter.is_valid({"delta": 101, "seq": 1}) is False
        assert counter.is_valid({"delta": -101, "seq": 1}) is False

    def test_counter_rejects_booleans_as_integers(self):
        assert Counter().is_valid({"delta": True, "seq": 1}) is False

    def test_counter_ignores_extra_keys(self):
        assert Counter().is_valid({"delta": 1, "seq": 1, "extra": "ok"}) is True

    def test_counter_chains_state(self):
        counter = Counter()
        counter.add_message({"delta": 1, "seq": 1})
        first = counter.head
        counter.add_message({"delta": 1, "seq": 2})
        assert counter.head != first
        assert counter.state() == {"seq": 2, "total": 2, "head": counter.head}

    def test_counter_reports_its_head_as_a_frontier(self):
        counter = Counter()
        assert counter.get_state_digests() == []
        counter.add_message({"delta": 1, "seq": 1})
        assert counter.get_state_digests() == [counter.head]

    def test_mirror_rejects_only_the_flag(self):
        mirror = Mirror()
        assert mirror.is_valid({"anything": 1}) is True
        assert mirror.is_valid({"reject_mirror": False}) is True
        assert mirror.is_valid({"reject_mirror": True}) is False

    def test_mirror_returns_nothing_from_add_message(self):
        assert Mirror().add_message({}, StateMemento.normalize(D1)) is None

    def test_replay_is_deterministic(self):
        """The same sequence twice produces identical state."""
        sequence = [
            {"delta": 5, "seq": 1},
            {"delta": -3, "seq": 2},
            {"delta": 1, "seq": 99},
            {"delta": 7, "seq": 3},
        ]
        runs = []
        for _ in range(2):
            registry = build_registry()
            for message in sequence:
                registry.apply(message)
            runs.append(
                (
                    registry.get("counter").state(),
                    registry.get("mirror").state(),
                )
            )
        assert runs[0] == runs[1]
