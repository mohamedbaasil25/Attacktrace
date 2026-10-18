"""Process graph: static P&ID edges (always kept) + Granger-learned edges (weighted lower)."""

import json
import warnings
from pathlib import Path

import networkx as nx
import numpy as np
from numpy.typing import NDArray
from statsmodels.tsa.stattools import grangercausalitytests

from app.sim import NODE_IDS, PID_EDGES
from app.sim.topology import NODE_BY_ID

STATIC_WEIGHT = 1.0
LEARNED_MAX_WEIGHT = 0.5  # learned edges never outweigh P&ID edges
GRANGER_ALPHA = 0.01
GRANGER_MAX_LAG = 4


def static_graph() -> nx.DiGraph:
    g: nx.DiGraph = nx.DiGraph()
    for nid in NODE_IDS:
        g.add_node(nid, type=str(NODE_BY_ID[nid].type))
    for a, b in PID_EDGES:
        g.add_edge(a, b, weight=STATIC_WEIGHT, kind="static")
    return g


def learn_granger_edges(
    data: NDArray[np.float64],
    names: tuple[str, ...] = NODE_IDS,
    max_lag: int = GRANGER_MAX_LAG,
    alpha: float = GRANGER_ALPHA,
) -> list[tuple[str, str, float]]:
    """Directed (cause, effect, weight) edges where `cause` Granger-causes `effect`.

    Tests run on first differences: closed-loop levels share trends and make every pair look
    causal on raw values.

    p-value is the best lag's F-test, Bonferroni-corrected over the lags tried. Weight maps
    -log10(p) into (0, LEARNED_MAX_WEIGHT].
    """
    data = np.diff(data, axis=0)
    edges: list[tuple[str, str, float]] = []
    for j, effect in enumerate(names):
        for i, cause in enumerate(names):
            if i == j:
                continue
            pair = data[:, [j, i]]
            if np.ptp(pair, axis=0).min() < 1e-9:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = grangercausalitytests(pair, maxlag=max_lag)
            except (np.linalg.LinAlgError, ValueError):
                continue
            p = min(res[lag][0]["ssr_ftest"][1] for lag in res) * max_lag
            if p < alpha:
                strength = min(1.0, -float(np.log10(max(p, 1e-300))) / 60.0)
                edges.append((cause, effect, LEARNED_MAX_WEIGHT * strength))
    return edges


def merge_graph(learned: list[tuple[str, str, float]]) -> nx.DiGraph:
    """Static edges always kept; learned edges added only where no static edge exists."""
    g = static_graph()
    for a, b, w in learned:
        if not g.has_edge(a, b):
            g.add_edge(a, b, weight=w, kind="learned")
    return g


def adjacency(
    g: nx.DiGraph, min_weight: float = 0.0, names: tuple[str, ...] = NODE_IDS
) -> NDArray[np.bool_]:
    """adj[i, j] = True when node j feeds node i (parents of i); diagonal always True."""
    idx = {n: i for i, n in enumerate(names)}
    adj = np.eye(len(names), dtype=bool)
    for a, b, d in g.edges(data=True):
        if d["weight"] >= min_weight:
            adj[idx[b], idx[a]] = True
    return adj


def save_graph(g: nx.DiGraph, path: Path) -> None:
    edges = [{"src": a, "dst": b, **d} for a, b, d in g.edges(data=True)]
    types = {n: d["type"] for n, d in g.nodes(data=True)}
    path.write_text(json.dumps({"nodes": list(g.nodes), "types": types, "edges": edges}, indent=1))


def load_graph(path: Path) -> nx.DiGraph:
    raw = json.loads(path.read_text())
    g: nx.DiGraph = nx.DiGraph()
    types = raw.get("types", {})
    for n in raw["nodes"]:
        g.add_node(n, type=types.get(n) or str(NODE_BY_ID[n].type))
    for e in raw["edges"]:
        g.add_edge(e["src"], e["dst"], weight=e["weight"], kind=e["kind"])
    return g


def learn_var_edges(
    data: NDArray[np.float64],
    names: tuple[str, ...],
    lags: int = 2,
    top_k: int = 4,
    min_t: float = 6.0,
) -> list[tuple[str, str, float]]:
    """Sparse directed edges from one multivariate lagged regression (conditional Granger).

    Each node's first difference is regressed on the lagged differences of every node at once, so
    a parent only counts if it adds information beyond the others. Pairwise Granger tests are
    far too slow and dense for ~50 nodes (about 4 minutes and 883 of 2450 edges on HAI). For each
    effect the `top_k` parents with the largest lag t-statistic above `min_t` are kept; weights
    map t into (0, LEARNED_MAX_WEIGHT].
    """
    d = np.diff(data, axis=0)
    d = (d - d.mean(axis=0)) / np.maximum(d.std(axis=0), 1e-9)
    n = d.shape[1]
    y = d[lags:]
    x = np.hstack([d[lags - lag : len(d) - lag] for lag in range(1, lags + 1)])
    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    s2 = ((y - x @ beta) ** 2).sum(axis=0) / (len(y) - x.shape[1])
    t = np.abs(beta / np.sqrt(np.outer(np.diag(xtx_inv), np.maximum(s2, 1e-12))))
    t_node = np.max([t[k * n : (k + 1) * n] for k in range(lags)], axis=0)  # (cause, effect)
    edges: list[tuple[str, str, float]] = []
    for j in range(n):
        order = [i for i in np.argsort(-t_node[:, j]) if i != j][:top_k]
        for i in order:
            if t_node[i, j] >= min_t:
                weight = LEARNED_MAX_WEIGHT * min(1.0, float(t_node[i, j]) / 50.0)
                edges.append((names[i], names[j], weight))
    return edges


def learned_graph(
    names: tuple[str, ...], types: dict[str, str], edges: list[tuple[str, str, float]]
) -> nx.DiGraph:
    """Graph for a plant without a published P&ID (HAI): learned edges only. Their kind stays
    "learned" so nothing downstream mistakes them for ground-truth plumbing."""
    g: nx.DiGraph = nx.DiGraph()
    for n in names:
        g.add_node(n, type=types[n])
    for a, b, w in edges:
        g.add_edge(a, b, weight=w, kind="learned")
    return g
