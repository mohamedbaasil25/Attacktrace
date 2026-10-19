import numpy as np
import pytest

from app.explain import explain
from app.graph import static_graph
from app.localize import Weights, build_incident, localize
from app.localize.locator import causal_term, first_crossings, onset_term, softmax
from app.propagate import reconstruct
from app.sim import NODE_IDS

N = len(NODE_IDS)
IDX = {n: i for i, n in enumerate(NODE_IDS)}
THR = np.full(N, 1.0)


def synthetic_chain(onsets: dict[str, int], peaks: dict[str, float], w: int = 60) -> np.ndarray:
    """Scores sit at 0.3; each listed node ramps up at its onset and holds its peak."""
    s = np.full((w, N), 0.3)
    for node, t0 in onsets.items():
        s[t0:, IDX[node]] = peaks[node]
    return s


CHAIN = {"LIT101": 10, "PLC1": 13, "MV101": 14, "FIT201": 18, "LIT301": 22}
PEAKS = {"LIT101": 3.0, "PLC1": 3.5, "MV101": 3.5, "FIT201": 4.0, "LIT301": 4.5}


def test_finds_true_origin_on_synthetic_chain() -> None:
    cands = localize(synthetic_chain(CHAIN, PEAKS), THR, static_graph())
    assert (
        cands[0].id == "LIT101"
    )  # earliest, most upstream node wins although LIT301 deviates more
    assert cands[0].type == "sensor"
    assert abs(sum(c.confidence for c in cands) - 1.0) < 1e-9
    assert cands[0].confidence == max(c.confidence for c in cands)


def test_weights_matter() -> None:
    w = synthetic_chain(CHAIN, PEAKS)
    by_dev = localize(w, THR, static_graph(), Weights(1.0, 0.0, 0.0))
    assert by_dev[0].id == "LIT301"  # deviation alone picks the loudest node


def test_first_crossings_requires_persistence() -> None:
    w = np.zeros((10, 2))
    w[2, 0] = 5.0  # one-sample blip
    w[4:, 1] = 5.0
    assert first_crossings(w, np.ones(2), persist=2).tolist() == [-1, 4]


def test_onset_term_rank_normalized() -> None:
    t = onset_term(np.array([5, 5, 9, -1]))
    assert t[0] == t[1] == 1.0 and 0 < t[2] < 1.0 and t[3] == 0.0
    assert onset_term(np.array([-1, -1])).tolist() == [0.0, 0.0]


def test_causal_term_favours_upstream() -> None:
    dev = np.zeros(N)
    dev[IDX["MV101"]] = dev[IDX["LIT101"]] = 1.0
    c = causal_term(static_graph(), dev)
    assert c.max() == pytest.approx(1.0)
    assert c[IDX["PLC1"]] > c[IDX["PLC2"]]  # PLC1 feeds the deviating nodes


def test_softmax_sums_to_one() -> None:
    p = softmax(np.array([0.1, 0.9, 0.5]))
    assert p.sum() == pytest.approx(1.0) and p.argmax() == 1


def test_propagation_orders_by_onset_and_links_edges() -> None:
    cross = np.full(N, -1, dtype=np.int64)
    for n, t in CHAIN.items():
        cross[IDX[n]] = t
    dev = np.zeros(N)
    prop = reconstruct(static_graph(), cross, dev, dt=0.5)
    assert [n.id for n in prop.nodes] == ["LIT101", "PLC1", "MV101", "FIT201", "LIT301"]
    assert prop.nodes[0].t == 0.0 and prop.nodes[1].t == 1.5 and prop.nodes[2].t == 2.0
    assert ("LIT101", "PLC1") in prop.edges and ("PLC1", "MV101") in prop.edges
    assert ("FIT201", "LIT301") in prop.edges
    assert reconstruct(static_graph(), np.full(N, -1), dev, 0.5).nodes == []


def test_explanation_templates() -> None:
    e = explain("LIT101", "low", False, ["PLC1", "MV101", "FIT201"])
    assert e.text == "Origin LIT101 (sensor) · spoof low → PLC1 → MV101 → T1 overflow risk"
    assert e.action == "Isolate LIT101 · PLC1 → manual" and e.mitre == "T0856"
    assert "frozen" in explain("LIT301", "high", True, []).text
    a = explain("P101", "low", False, ["LIT101"])
    assert "forced off" in a.text and a.mitre == "T0831" and a.action.startswith("Lock P101")
    c = explain("PLC2", "high", False, [])
    assert c.mitre == "T0855" and "restore setpoint" in c.action
    assert (
        max(
            len(explain(n, d, False, ["A", "B", "C"]).text.splitlines())
            for n in NODE_IDS
            for d in ("low", "high")
        )
        == 1
    )


def test_build_incident_end_to_end() -> None:
    scores = np.vstack([synthetic_chain(CHAIN, PEAKS, 120), np.full((5, N), 0.3)])
    x = np.zeros((len(scores), N))
    x[:, IDX["LIT101"]] = 30.0  # reads low vs mu = 50
    mu = np.full(N, 50.0)
    inc = build_incident(
        scores, np.zeros_like(scores), x, alert_idx=70, mu=mu, node_thr=THR, graph=static_graph()
    )
    assert inc.candidates[0].id == "LIT101"
    assert inc.explanation.text.startswith("Origin LIT101 (sensor) · frozen")  # constant reading
    assert inc.explanation.mitre == "T0856"
    assert inc.window[0] == 0 and inc.window[1] <= len(scores)
    assert {n.id for n in inc.propagation.nodes} == set(CHAIN)


def test_deviation_horizon_measures_initial_jump() -> None:
    from app.localize.locator import deviation_term

    w = np.full((30, N), 0.3)
    a, b = IDX["LIT101"], IDX["PLC1"]
    w[5:, a] = 3.0  # origin: jumps at once, then holds
    w[6:, b] = np.linspace(1.5, 12.0, 24)  # downstream: grows, ends far larger
    cross = first_crossings(w, THR, persist=2)
    full = deviation_term(w, THR)
    early = deviation_term(w, THR, cross, horizon=2)
    assert full[b] > full[a] and early[a] > early[b]


def test_breakdown_sums_to_the_candidates_own_score() -> None:
    """Phase 11 B1: contributions are weight*term; they add up to the node's own raw score."""
    cands = localize(synthetic_chain(CHAIN, PEAKS), THR, static_graph())
    for c in cands:
        assert sum(c.contributions()) == pytest.approx(c.raw_score)
        assert c.weights == Weights()
    assert cands[0].score == pytest.approx(cands[0].raw_score)  # no tie here: score is unchanged


def test_tie_rule_only_permutes_scores_so_the_breakdown_stays_honest() -> None:
    """Inside a tie group the ranked score is another member's raw score; the breakdown still
    shows each node's own terms, and the total of ranked scores equals the total of raw scores."""
    s = np.full((60, N), 0.3)
    for node in ("LIT101", "PLC1"):  # same-sample onset: a near-tie
        s[10:, IDX[node]] = 3.0
    cands = localize(s, THR, static_graph())
    assert sum(c.score for c in cands) == pytest.approx(sum(c.raw_score for c in cands))
    for c in cands:
        assert sum(c.contributions()) == pytest.approx(c.raw_score)


def test_breakdown_does_not_change_the_ranking() -> None:
    w = synthetic_chain(CHAIN, PEAKS)
    a = localize(w, THR, static_graph())
    b = localize(w, THR, static_graph(), Weights(0.6, 0.2, 0.2))
    assert [c.id for c in a] == [c.id for c in b]
    assert [c.confidence for c in a] == [c.confidence for c in b]
