"""Attack path reconstruction: deviating nodes ordered by onset, joined by shortest paths."""

from dataclasses import dataclass
from itertools import pairwise

import networkx as nx
import numpy as np
from numpy.typing import NDArray

from app.sim import NODE_IDS
from app.sim.topology import SECONDARY_EDGES

F64 = NDArray[np.float64]

SECONDARY_COST = 3.0


@dataclass(frozen=True)
class PathNode:
    id: str
    t: float  # seconds after the first onset
    deviation: float


@dataclass(frozen=True)
class Propagation:
    nodes: list[PathNode]
    edges: list[tuple[str, str]]


def _cost(graph: nx.DiGraph) -> nx.DiGraph:
    g: nx.DiGraph = graph.copy()
    for _, _, d in g.edges(data=True):
        d["cost"] = 1.0 / max(d["weight"], 1e-6)
    return g


def _shortest(g: nx.DiGraph, a: str, b: str) -> list[str] | None:
    for graph in (g, g.to_undirected()):  # prefer the causal direction, else any connection
        try:
            return list(nx.shortest_path(graph, a, b, weight="cost"))
        except nx.NetworkXNoPath:
            continue
    return None


def hop_distance(graph: nx.DiGraph, origin: str) -> dict[str, float]:
    """Propagation distance from `origin` over the P&ID: 1 per main edge, SECONDARY_COST per
    weak coupling, so a controller outranks a barely-coupled sensor that is also one edge away."""
    g: nx.DiGraph = nx.DiGraph()
    g.add_nodes_from(graph.nodes)
    has_static = any(d.get("kind") == "static" for _, _, d in graph.edges(data=True))
    for a, b, d in graph.edges(data=True):
        if d.get("kind") == "static" or not has_static:
            g.add_edge(a, b, cost=SECONDARY_COST if (a, b) in SECONDARY_EDGES else 1.0)
    return dict(nx.single_source_dijkstra_path_length(g, origin, weight="cost"))


def reconstruct(
    graph: nx.DiGraph,
    onset_idx: NDArray[np.int64],
    deviation: F64,
    dt: float,
    names: tuple[str, ...] = NODE_IDS,
    origin: str | None = None,
) -> Propagation:
    """`onset_idx[i] < 0` means node i never deviated and is excluded.

    Order: onset sample, then (tie rule) hops from the origin along the process graph, so
    nodes that deviate within the same 0.5 s sample still appear cause-first, then deviation.
    """
    hit = [i for i in range(len(names)) if onset_idx[i] >= 0]
    hops = hop_distance(graph, origin) if origin else {}
    far = float(len(graph)) * SECONDARY_COST
    hit.sort(key=lambda i: (onset_idx[i], hops.get(names[i], far), -deviation[i]))
    if not hit:
        return Propagation([], [])
    t0 = int(onset_idx[hit[0]])
    nodes = [
        PathNode(names[i], round((int(onset_idx[i]) - t0) * dt, 3), float(deviation[i]))
        for i in hit
    ]
    g = _cost(graph)
    edges: list[tuple[str, str]] = []
    for a, b in pairwise(hit):
        path = _shortest(g, names[a], names[b])
        if path is None:
            continue
        for e in pairwise(path):
            if e not in edges:
                edges.append(e)
    return Propagation(nodes, edges)
