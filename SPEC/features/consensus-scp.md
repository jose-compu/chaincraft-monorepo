# consensus.scp

**Release:** 1.4.0

Pedagogical Stellar Consensus Protocol (SCP) implementing Federated Byzantine Agreement (FBA) via quorum slices. Each node declares its own set of trusted peers (slices). A statement is accepted when a quorum intersecting every slice threshold is met. No global 2f+1 fixed replica list (see PBFT #6).

This is **not** a full Stellar Core implementation, live overlay, or UNL-based system. It is a single pedagogical object driven by messages with no wall-clock, no real network flooding, and deterministic vectors.

See issue [#22](https://github.com/jose-compu/chaincraft-monorepo/issues/22).

## Parameters

| Name | Default | Rule |
|---|---|---|
| `node` | `n0` | Local node id. |
| `slices` | `[]` | Array of quorum slices for this node. Each slice is an array of node ids (including self). |

Slices define the trust graph. A valid quorum for a node is a set that contains a slice for every "blocking set" or uses the recursive quorum definition from the SCP paper. For the pedagogical version we use a simplified threshold model derived from slices.

Construction with invalid slices (empty, missing self, duplicates) is rejected.

## State

The object maintains:

- Current ballot (counter, value)
- Phase: nominate | prepare | confirm | externalize
- Accepted statements per phase
- Quorum thresholds computed from slices

## Messages

Messages carry a `consensus: "scp"`, `phase`, `ballot` `{counter, value}`, `node`, and optional `statements` or `quorum` proof.

Example:

```json
{
  "consensus": "scp",
  "phase": "nominate",
  "ballot": {"counter": 1, "value": "hello"},
  "node": "n0",
  "quorum": ["n0", "n1", "n2"]
}
```

Phases follow Stellar SCP:

- **Nominate**: Propose values, federated voting on candidates.
- **Prepare**: Prepare a ballot.
- **Confirm**: Confirm a ballot once prepared by quorum.
- **Externalize**: Externalize the confirmed value (final).

A statement is only accepted if `is_valid` passes structural checks **and** `_is_quorum_valid` (local node in quorum **and** at least one slice has strict majority intersection). This is a pedagogical simplification of the full SCP quorum intersection algorithm.

## `is_valid` and `add_message`

- Validate structure, ballot monotonicity, phase transitions.
- `add_message` updates local state only if the message's quorum is valid w.r.t. the receiver's slices.
- Quorum check: a set of nodes forms a quorum if for every slice of the node, the set intersects it in a sufficient way (simplified for pedagogy: majority in each slice or full recursive definition).
- Vectors will test:
  - Agreement on single value across nodes with overlapping slices.
  - Blocked split-vote (no quorum possible).
  - Higher ballot aborts lower one.

## Vectors

`conformance/vectors/consensus-scp.json` will contain test vectors for the three cases listed in the issue: successful agreement, blocked split, and ballot abort.

Implementation will be added to `python/chaincraft/`, `rust/src/`, `typescript/src/` as `consensus_scp.py`, `consensus_scp.rs`, `consensusScp.ts` following the pattern of `consensus_avalanche.*` and updating the feature manifests.

This spec will be refined as the implementation progresses.
