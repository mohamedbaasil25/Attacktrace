"""Multi-incident tracking, Phase 1 (SIM/LIVE only; `engine_hai.py` is untouched).

`Engine._open` can hold more than one concurrently open incident. Admission is driven by
per-node persistence crossings (`node_crossed`, computed in `step_sample`) resolved through
`_fold_target`: a node folds into an already-open incident when it is within `settings.zone_hops`
undirected graph hops of a node already VERIFIED to belong to that incident (`op.member_nodes` --
seeded with the triggering node at creation, grown one hop at a time by each later fold), else it
opens a new one. `member_nodes` is deliberately narrower than the localizer's one-shot `path`: an
earlier version anchored the check to `path` and later to the origin alone, and both broke --
`path` over-reaches (it can include weakly-correlated nodes that never independently cross their
own threshold, so a mature incident's `path` can span most of this small plant and swallow a
second, unrelated attack), and the origin alone under-reaches (it can't be walked to by a real
multi-hop downstream propagation chain several hops away, which a LIVE regression test caught:
a single P101 attack's own effects reached P301, 3 hops away, and were split into two incidents).

Tests at two levels:
  - `_fold_target` directly, against hand-seeded `_Open` entries (deterministic, independent of
    the real localizer -- a freshly created incident's `path`/analysis depends on the
    detector/plant's clean-window output, which we don't want to bake into these assertions).
  - `_advance_incident` end-to-end for the parts that don't depend on analysis content:
    new-incident creation, id uniqueness, and isolate() targeting the right entry among several
    open.
"""

import time

import numpy as np
from numpy.typing import NDArray

from app.engine import Engine, _Open, _severity_key
from app.schemas import Incident, OriginCandidate, PathStep
from app.sim import NODE_IDS

ZEROS = np.zeros(len(NODE_IDS))


def _node_crossed(node: str | None) -> NDArray[np.bool_]:
    mask = np.zeros(len(NODE_IDS), dtype=bool)
    if node is not None:
        mask[NODE_IDS.index(node)] = True
    return mask


def _inc(id_: str, member_ids: list[str], status: str = "open") -> Incident:
    return Incident(
        id=id_,
        status=status,  # type: ignore[arg-type]
        detected_at=0.0,
        origin=[OriginCandidate(id=member_ids[0], type="sensor", confidence=0.5)]
        if member_ids
        else [],
        path=[PathStep(id=n, t=0.0, deviation=1.0) for n in member_ids],
        path_edges=[],
        explanation="",
        action="",
        mitre="T0856",
        mitre_name="",
        baseline_alarms=[],
    )


def _seed_open(engine: Engine, id_: str, member_ids: list[str], status: str = "open") -> None:
    inc = _inc(id_, member_ids, status)
    engine._open[id_] = _Open(
        inc=inc, alert_k=0, alarms=set(member_ids), member_nodes=set(member_ids)
    )
    engine.incidents.append(inc)


def _tick(engine: Engine, node: str | None) -> None:
    engine._advance_incident(
        engine._k, node is not None, _node_crossed(node), time.time(), ZEROS, ZEROS
    )
    engine._k += 1


# ------------------------------------------------------------------- _fold_target (unit level)


def test_fold_target_folds_a_direct_neighbour(engine: Engine) -> None:
    _seed_open(engine, "seed_a", ["LIT101"])
    assert engine._fold_target("MV101") == "seed_a"  # 1 hop from LIT101 on the P&ID


def test_fold_target_folds_the_incidents_own_node(engine: Engine) -> None:
    _seed_open(engine, "seed_a", ["LIT101"])
    assert engine._fold_target("LIT101") == "seed_a"  # distance 0: re-crossing the origin itself


def test_fold_target_returns_none_beyond_zone_hops(engine: Engine) -> None:
    _seed_open(engine, "seed_a", ["LIT101"])
    # PLC2 is 3 undirected hops from LIT101 (LIT101-FIT201-LIT301-PLC2) -- past the default
    # zone_hops=2 -- the physically-distant "quiet second attack" case from the architecture note.
    assert engine._fold_target("PLC2") is None


def test_fold_target_ignores_closed_and_contained_incidents(engine: Engine) -> None:
    _seed_open(engine, "seed_closed", ["LIT101"], status="closed")
    _seed_open(engine, "seed_contained", ["LIT101"], status="contained")
    assert engine._fold_target("LIT101") is None


def test_fold_target_respects_the_configured_zone_hops(engine: Engine) -> None:
    _seed_open(engine, "seed_a", ["LIT101"])
    engine.settings.zone_hops = 0
    assert engine._fold_target("MV101") is None  # 1 hop no longer close enough
    assert engine._fold_target("LIT101") == "seed_a"  # distance 0 always folds


def test_fold_target_walks_a_multi_hop_propagation_chain(engine: Engine) -> None:
    """Regression: a single attack's own downstream effects can independently cross PERSIST
    several hops from the origin (seen in LIVE: a P101 attack reached P301, 3 hops away). Each
    hop only needs to be near an ALREADY-ADMITTED member, not near the origin directly, so the
    chain can walk arbitrarily far one verified hop at a time."""
    # P101 (origin) -> FIT201 (1 hop) -> LIT301 (1 hop from FIT201) each already admitted.
    _seed_open(engine, "seed_a", ["P101", "FIT201", "LIT301"])
    # P301 is 3 hops from P101 directly, but 1 hop from LIT301, which is already a member.
    assert engine._fold_target("P301") == "seed_a"


def test_fold_target_does_not_use_the_wider_localized_path(engine: Engine) -> None:
    """`member_nodes` is deliberately narrower than `inc.path`: a node that only appears in the
    localizer's one-shot path (never independently verified via its own crossing) must not let a
    distant node fold in through it."""
    inc = _inc("seed_a", ["LIT101"])
    inc.path = [
        PathStep(id="LIT101", t=0.0, deviation=1.0),
        PathStep(id="PLC2", t=6.0, deviation=0.5),
    ]
    engine._open["seed_a"] = _Open(inc=inc, alert_k=0, alarms={"LIT101"}, member_nodes={"LIT101"})
    engine.incidents.append(inc)
    # P301 is 1 hop from PLC2 (in `path` but not `member_nodes`) and 3 hops from LIT101 (the only
    # real member) -- must NOT fold, even though PLC2 appears in the wider localized path.
    assert engine._fold_target("P301") is None


# --------------------------------------------------------------- _advance_incident (end to end)


def test_a_nearby_crossing_folds_into_the_open_incident_not_a_new_one(engine: Engine) -> None:
    _seed_open(engine, "seed_a", ["LIT101"])
    _tick(engine, "MV101")
    assert len(engine._open) == 1


def test_a_distant_crossing_opens_a_second_incident_alongside_the_first(engine: Engine) -> None:
    _seed_open(engine, "seed_a", ["LIT101"])
    _tick(engine, "PLC2")
    assert len(engine._open) == 2


def test_incident_ids_stay_unique_across_sequential_opens(engine: Engine) -> None:
    seen: list[str] = []
    for node in ("LIT101", "PLC2", "P301"):
        engine._open.clear()  # isolate each creation from the others' fold check
        _tick(engine, node)
        seen.extend(engine._open.keys())
    assert len(set(seen)) == 3


def test_isolate_targets_the_correct_incident_among_several_open(engine: Engine) -> None:
    _seed_open(engine, "seed_a", ["LIT101"])
    _seed_open(engine, "seed_b", ["PLC2"])

    applied, reason = engine.isolate("seed_b", "P301", operator="Alex")
    assert applied and reason is None
    assert engine._open["seed_b"].inc.isolated_by == "Alex"
    assert engine._open["seed_a"].inc.isolated_by is None
    assert engine._open["seed_a"].isolated_t is None


# ------------------------------------------------------------------------- severity ordering


def test_severity_ordering_matches_the_documented_key() -> None:
    def inc(id_: str, ambiguous: bool, confidence: float, detected_at: float) -> Incident:
        return Incident(
            id=id_,
            status="open",
            detected_at=detected_at,
            origin=[OriginCandidate(id="LIT101", type="sensor", confidence=confidence)],
            path=[],
            path_edges=[],
            explanation="",
            action="",
            mitre="T0856",
            mitre_name="Spoof Reporting Message",
            baseline_alarms=[],
            ambiguous=ambiguous,
        )

    low_conf_ambiguous = inc("inc_amb", True, 0.4, 100.0)
    high_conf_early = inc("inc_a", False, 0.9, 50.0)
    high_conf_late = inc("inc_b", False, 0.9, 150.0)
    mid_conf = inc("inc_c", False, 0.6, 10.0)

    ordered = sorted(
        [mid_conf, high_conf_late, low_conf_ambiguous, high_conf_early], key=_severity_key
    )
    assert [i.id for i in ordered] == ["inc_amb", "inc_a", "inc_b", "inc_c"]
