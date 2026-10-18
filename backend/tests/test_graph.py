import numpy as np

from app.graph import adjacency, learn_granger_edges, merge_graph, static_graph
from app.graph.builder import LEARNED_MAX_WEIGHT
from app.sim import NODE_IDS, PID_EDGES


def test_static_graph_matches_pid() -> None:
    g = static_graph()
    assert set(g.nodes) == set(NODE_IDS)
    assert set(g.edges) == set(PID_EDGES)


def test_granger_finds_lagged_cause() -> None:
    rng = np.random.default_rng(0)
    n = 1500
    a = rng.normal(size=n)
    b = np.zeros(n)
    for t in range(2, n):
        b[t] = 0.8 * a[t - 2] + 0.1 * rng.normal()
    c = rng.normal(size=n)
    data = np.cumsum(np.column_stack([a, b, c]), axis=0)  # diffed again inside → a, b, c
    data = np.vstack([np.zeros(3), data])
    edges = {(s, d): w for s, d, w in learn_granger_edges(data, names=("a", "b", "c"))}
    assert ("a", "b") in edges
    assert ("c", "b") not in edges and ("b", "a") not in edges


def test_merge_keeps_static_and_downweights_learned() -> None:
    learned = [("PLC1", "PLC2", 0.4), ("LIT101", "PLC1", 0.4)]  # second duplicates a P&ID edge
    g = merge_graph(learned)
    assert set(PID_EDGES) <= set(g.edges)
    assert g["LIT101"]["PLC1"]["kind"] == "static" and g["LIT101"]["PLC1"]["weight"] == 1.0
    assert g["PLC1"]["PLC2"]["kind"] == "learned"
    assert all(
        d["weight"] <= LEARNED_MAX_WEIGHT for *_, d in g.edges(data=True) if d["kind"] == "learned"
    )


def test_adjacency_lists_parents() -> None:
    adj = adjacency(static_graph())
    i = {n: k for k, n in enumerate(NODE_IDS)}
    assert adj[i["MV101"], i["PLC1"]] and not adj[i["PLC1"], i["MV101"]]
    assert adj.diagonal().all()
    weak = adjacency(merge_graph([("PLC1", "PLC2", 0.1)]), min_weight=0.25)
    assert not weak[i["PLC2"], i["PLC1"]]
