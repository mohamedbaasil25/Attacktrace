"""Near-tied onsets: the tie rule must put the cause first, in the order effects propagate."""

import numpy as np

from app.graph import static_graph
from app.localize import localize
from app.localize.locator import (
    break_ties,
    combine_onsets,
    first_crossings,
    step_onsets,
)
from app.propagate import reconstruct
from app.sim import NODE_IDS

N = len(NODE_IDS)
IDX = {n: i for i, n in enumerate(NODE_IDS)}
THR = np.full(N, 1.0)
W = 60


def window(steps: dict[str, int], peaks: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """Scores sit at 0.3 and jump to `peaks[node]` at `steps[node]`; the raw error spikes
    to 20 on that one sample (as a spoofed reading or forced actuator does)."""
    scores = np.full((W, N), 0.3)
    errors = np.zeros((W, N))
    for node, t0 in steps.items():
        scores[t0:, IDX[node]] = peaks[node]
        errors[t0, IDX[node]] = 20.0
    return scores, errors


def top(steps: dict[str, int], peaks: dict[str, float]) -> list[str]:
    s, e = window(steps, peaks)
    return [c.id for c in localize(s, THR, static_graph(), errors=e)]


def test_sensor_wins_tie_with_its_plc_even_when_plc_scores_higher() -> None:
    # Sensor offset: LIT101 and PLC1 jump on the same sample; PLC1 amplifies the error.
    ranked = top(
        {"LIT101": 20, "PLC1": 20, "MV101": 21}, {"LIT101": 3.0, "PLC1": 3.4, "MV101": 2.0}
    )
    assert ranked[0] == "LIT101"
    assert ranked.index("PLC1") < ranked.index("MV101")


def test_strictly_earlier_onset_beats_signal_order() -> None:
    # Rogue setpoint: PLC1 moves one sample before the sensor it controls.
    ranked = top(
        {"PLC1": 20, "LIT101": 21, "MV101": 21}, {"PLC1": 3.0, "LIT101": 3.3, "MV101": 3.0}
    )
    assert ranked[0] == "PLC1"


def test_actuator_beats_the_process_sensors_it_drives() -> None:
    # Forced pump: P101, FIT201 and PIT301 all cross together and PIT301 is loudest.
    ranked = top(
        {"P101": 20, "FIT201": 20, "PIT301": 20},
        {"P101": 3.0, "FIT201": 3.2, "PIT301": 3.9},
    )
    assert ranked[:3] == ["P101", "FIT201", "PIT301"]  # cause first, then what it drives


def test_clearly_weaker_node_is_not_pulled_into_the_tie() -> None:
    ranked = top({"LIT301": 20, "PLC2": 20}, {"LIT301": 9.0, "PLC2": 1.2})
    assert ranked[0] == "LIT301"


def test_tie_rule_keeps_confidence_monotonic() -> None:
    s, e = window({"LIT101": 20, "PLC1": 20}, {"LIT101": 3.0, "PLC1": 3.4})
    conf = [c.confidence for c in localize(s, THR, static_graph(), errors=e)]
    assert conf == sorted(conf, reverse=True)


def test_break_ties_is_deterministic_and_total() -> None:
    score = np.array([0.9, 0.8, 0.8, 0.1])
    conf = np.array([0.4, 0.3, 0.3, 0.0])
    onset = np.array([5, 5, 5, -1], dtype=np.int64)
    types = ["actuator", "controller", "sensor", "sensor"]
    down = [set(), set(), set(), set()]
    order, s2, _ = break_ties(score, conf, onset, types, down)
    assert order == [2, 1, 0, 3]  # sensor, controller, actuator; unrelated last
    assert sorted(s2[:3], reverse=True) == list(s2[[2, 1, 0]])


def test_step_onsets_and_combination() -> None:
    e = np.zeros((10, 3))
    e[4, 0] = 9.0
    e[2, 1] = 5.0  # below the step threshold: not an abrupt jump
    steps = step_onsets(e)
    assert steps.tolist() == [4, -1, -1]
    ewma = np.array([6, 3, -1], dtype=np.int64)
    assert combine_onsets(ewma, steps).tolist() == [4, 3, -1]


def test_node_already_elevated_when_window_opens_is_not_a_cause() -> None:
    s, e = window({"LIT101": 20}, {"LIT101": 3.0})
    s[:, IDX["FIT201"]] = 2.0  # above threshold from the very first sample
    cands = {c.id: c for c in localize(s, THR, static_graph(), errors=e)}
    assert cands["FIT201"].onset_idx is None
    assert first_crossings(s, THR)[IDX["FIT201"]] == 0  # raw crossing exists, then discarded


def test_path_orders_same_sample_onsets_cause_first() -> None:
    onset = np.full(N, -1, dtype=np.int64)
    for n in ("LIT101", "PLC1", "MV101", "P101", "FIT201", "PIT301"):
        onset[IDX[n]] = 20  # all within one 0.5 s sample
    dev = np.zeros(N)
    dev[IDX["PIT301"]] = 1.0  # loudest node must not jump the queue
    prop = reconstruct(static_graph(), onset, dev, 0.5, origin="LIT101")
    order = [n.id for n in prop.nodes]
    assert order[0] == "LIT101" and order[1] == "PLC1"
    assert order.index("MV101") < order.index("FIT201") < order.index("PIT301")
    assert order.index("P101") < order.index("FIT201")
    assert {n.t for n in prop.nodes} == {0.0}  # still honest about timing resolution


def test_gate_flags_close_top_two_and_never_reorders() -> None:
    """Phase 11 B2: ambiguity is a read-only flag on the ranked list."""
    from app.engine import is_ambiguous
    from app.localize.locator import Candidate

    def cand(i: str, conf: float) -> Candidate:
        return Candidate(i, "sensor", conf, conf, 0.0, None, 0.0)

    close = [cand("A", 0.40), cand("B", 0.35), cand("C", 0.25)]
    clear = [cand("A", 0.80), cand("B", 0.15), cand("C", 0.05)]
    assert is_ambiguous(close, 0.21) and not is_ambiguous(clear, 0.21)
    assert not is_ambiguous(close, 0.0)  # margin 0 never flags
    assert [c.id for c in close] == ["A", "B", "C"]  # untouched
    assert not is_ambiguous([cand("A", 1.0)], 0.21)  # a single candidate cannot be ambiguous
