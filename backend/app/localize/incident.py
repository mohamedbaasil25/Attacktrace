"""Incident assembly: ranked origins + propagation path + explanation for one alert."""

from dataclasses import dataclass

import networkx as nx
import numpy as np
from numpy.typing import NDArray

from app.explain.templates import Explanation, explain
from app.localize.locator import Candidate, Weights, localize
from app.propagate.path import Propagation, reconstruct
from app.sim import NODE_IDS
from app.sim.topology import NODE_BY_ID, NodeType

F64 = NDArray[np.float64]

SAMPLE_DT = 0.5  # detector sample period (2 Hz)
LOOKBACK_S = 40.0  # incident window starts this long before the alert...
FORWARD_S = 10.0  # ...and ends this long after it (the time-to-localize cost)
RECENT = 10  # samples used to read the origin's current value / spot a frozen sensor


@dataclass(frozen=True)
class Incident:
    alert_idx: int
    window: tuple[int, int]  # [lo, hi) sample indices of the incident window
    candidates: list[Candidate]  # ranked, best first
    propagation: Propagation
    explanation: Explanation


def build_incident(
    scores: F64,
    errors: F64,
    x: F64,
    alert_idx: int,
    mu: F64,
    node_thr: F64,
    graph: nx.DiGraph,
    weights: Weights | None = None,
    dt: float = SAMPLE_DT,
) -> Incident:
    """`scores`/`errors`/`x` are (T, N) per-node scores, raw errors and reported values."""
    lo = max(0, alert_idx - round(LOOKBACK_S / dt))
    hi = min(len(scores), alert_idx + round(FORWARD_S / dt) + 1)
    window = scores[lo:hi]
    cands = localize(window, node_thr, graph, weights, errors=errors[lo:hi])
    by_node = sorted(cands, key=lambda c: NODE_IDS.index(c.id))
    cross = np.array([-1 if c.onset_idx is None else c.onset_idx for c in by_node], dtype=np.int64)
    dev = np.array([c.deviation for c in by_node])
    prop = reconstruct(graph, cross, dev, dt, origin=cands[0].id)

    origin = cands[0]
    k = NODE_IDS.index(origin.id)
    recent = x[max(lo, hi - RECENT) : hi, k]
    direction = "low" if recent.mean() < mu[k] else "high"
    frozen = NODE_BY_ID[origin.id].type is NodeType.SENSOR and float(np.ptp(recent)) == 0.0
    t_o = origin.onset_idx if origin.onset_idx is not None else -1
    downstream = [
        n.id for n in prop.nodes if n.id != origin.id and cross[NODE_IDS.index(n.id)] >= t_o
    ]
    return Incident(
        alert_idx, (lo, hi), cands, prop, explain(origin.id, direction, frozen, downstream)
    )
