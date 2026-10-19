"""Origin ranking: score_i = w1*deviation_i + w2*onset_i + w3*causal_i. Pure functions."""

from dataclasses import dataclass

import networkx as nx
import numpy as np
from numpy.typing import NDArray

from app.sim import NODE_IDS
from app.sim.topology import NODE_BY_ID

F64 = NDArray[np.float64]

CROSS_PERSIST = 2  # consecutive samples above the node threshold to count as an onset
PPR_ALPHA = 0.85
DEV_HORIZON: int | None = 2  # samples after onset over which deviation is measured
TEMPERATURE = 0.062  # softmax temperature, calibrated by log-loss on tuning attacks
STEP_THR = 7.0  # raw normalized error that marks an abrupt jump (clean maximum is about 5)
TIE_FLOOR = 0.6  # a tie partner must score at least this fraction of the best candidate
TIE_ONSET = 1  # ...and have an onset within this many samples (0.5 s each) of its neighbour
SIGNAL_RANK = {"sensor": 0, "controller": 1, "actuator": 2}  # sensor -> PLC -> actuator


@dataclass(frozen=True)
class Weights:
    deviation: float = 0.6
    onset: float = 0.2
    causal: float = 0.2


@dataclass(frozen=True)
class Candidate:
    id: str
    type: str
    score: float
    confidence: float
    deviation: float
    onset_idx: int | None  # sample index within the incident window; None = never crossed
    causal: float
    # Own, unadjusted terms (read-only additions; ranking never uses them after the fact).
    onset: float = 0.0  # normalized onset term (1 = earliest crossing)
    raw_score: float = 0.0  # weights . (deviation, onset, causal) for this node alone
    weights: Weights = Weights()

    def contributions(self) -> tuple[float, float, float]:
        """(deviation, onset, causal) contributions to `raw_score`. They equal `score` unless the
        tie rule reordered this candidate, which hands out the group's scores in a new order."""
        w = self.weights
        return w.deviation * self.deviation, w.onset * self.onset, w.causal * self.causal


def deviation_term(
    window: F64, node_thr: F64, cross: NDArray[np.int64] | None = None, horizon: int | None = None
) -> F64:
    """(W, N) scores → (N,) peak per node relative to its threshold, log-compressed so one
    node with a huge raw error cannot drown out the onset and causal terms; max-normalized.

    With `horizon`, a node's peak is taken over `horizon` samples from its own onset: the
    initial jump of the true origin, before downstream amplification inflates its neighbours."""
    peaks = window.max(axis=0)
    if cross is not None and horizon is not None:
        for j in np.flatnonzero(cross >= 0):
            peaks[j] = window[cross[j] : cross[j] + horizon, j].max()
    peak = np.log1p(peaks / node_thr)
    return np.asarray(peak / max(float(peak.max()), 1e-12), dtype=np.float64)


def first_crossings(window: F64, node_thr: F64, persist: int = CROSS_PERSIST) -> NDArray[np.int64]:
    """(N,) first sample where a node stayed above threshold for `persist` samples, else -1."""
    above = window > node_thr
    out = np.full(window.shape[1], -1, dtype=np.int64)
    for j in range(window.shape[1]):
        run = 0
        for i, a in enumerate(above[:, j]):
            run = run + 1 if a else 0
            if run >= persist:
                out[j] = i - persist + 1
                break
    return out


def step_onsets(errors: F64, thr: float = STEP_THR) -> NDArray[np.int64]:
    """(N,) first sample whose raw error jumps past `thr` (spoofed readings and forced
    actuators step instantly; EWMA-smoothed scores would blur which node moved first)."""
    hit = errors >= thr
    return np.where(hit.any(axis=0), hit.argmax(axis=0), -1).astype(np.int64)


def combine_onsets(a: NDArray[np.int64], b: NDArray[np.int64]) -> NDArray[np.int64]:
    """Elementwise earliest valid onset (-1 = none)."""
    return np.where(a < 0, b, np.where(b < 0, a, np.minimum(a, b))).astype(np.int64)


def break_ties(
    score: F64,
    conf: F64,
    onset: NDArray[np.int64],
    types: list[str],
    downstream: list[set[int]],
) -> tuple[list[int], F64, F64]:
    """Order candidates best-first, resolving near-ties by cause and effect.

    The near-tie group is every candidate scoring at least TIE_FLOOR of the best whose
    onset is within TIE_ONSET samples (0.5 s each) of the best one's. Inside the group the
    order is: earliest onset sample, then most group members reachable downstream along the
    P&ID (a cause comes before the nodes it drives), then signal order sensor -> controller
    -> actuator (a controller simply follows its sensor, an actuator its controller), then
    score. The group keeps its descending score/confidence values in the new order, so
    confidences stay monotonic.
    """
    order = sorted(range(len(score)), key=lambda i: -score[i])
    top = order[0]
    group = [top]
    if onset[top] >= 0:
        group += [
            i
            for i in order[1:]
            if score[i] >= TIE_FLOOR * score[top]
            and onset[i] >= 0
            and abs(int(onset[i]) - int(onset[top])) <= TIE_ONSET
        ]
    members = set(group)
    late = int(onset.max()) + 1
    group.sort(
        key=lambda i: (
            onset[i] if onset[i] >= 0 else late,
            -len(downstream[i] & members),
            SIGNAL_RANK[types[i]],
            -score[i],
        )
    )
    new_order = group + [i for i in order if i not in members]
    s, c = np.sort(score[group])[::-1], np.sort(conf[group])[::-1]
    score2, conf2 = score.copy(), conf.copy()
    for slot, i in enumerate(group):
        score2[i], conf2[i] = s[slot], c[slot]
    return new_order, score2, conf2


def onset_term(cross: NDArray[np.int64]) -> F64:
    """Earlier first-crossing = higher. Rank-normalized over crossing nodes (ties share rank)."""
    out = np.zeros(len(cross))
    hit = cross >= 0
    m = int(hit.sum())
    if m == 0:
        return out
    times = cross[hit]
    ranks = np.array([np.sum(np.unique(times) < t) for t in times])
    out[hit] = (len(np.unique(times)) - ranks) / len(np.unique(times))
    return out


def causal_term(graph: nx.DiGraph, deviation: F64, names: tuple[str, ...] = NODE_IDS) -> F64:
    """Personalized PageRank on the reversed graph, seeded by deviation: mass flows from
    deviating nodes back toward their causes, so upstream nodes score high."""
    seed = {n: float(d) for n, d in zip(names, deviation, strict=True)}
    if sum(seed.values()) <= 0:
        seed = dict.fromkeys(names, 1.0)
    pr = nx.pagerank(
        graph.reverse(copy=True), alpha=PPR_ALPHA, personalization=seed, weight="weight"
    )
    v = np.array([pr[n] for n in names])
    return np.asarray(v / max(float(v.max()), 1e-12), dtype=np.float64)


def softmax(x: F64, temperature: float = TEMPERATURE) -> F64:
    z = (x - x.max()) / temperature
    e = np.exp(z)
    return np.asarray(e / e.sum(), dtype=np.float64)


def localize(
    window: F64,
    node_thr: F64,
    graph: nx.DiGraph,
    weights: Weights | None = None,
    names: tuple[str, ...] = NODE_IDS,
    errors: F64 | None = None,
    types: list[str] | None = None,
) -> list[Candidate]:
    """Rank candidate origin nodes for an incident window of node scores (W, N). `errors`
    (same window, raw per-sample errors) sharpens onsets to the exact sample of a jump."""
    weights = weights or Weights()
    cross = first_crossings(window, node_thr)
    if errors is not None:
        cross = combine_onsets(cross, step_onsets(errors))
    cross = np.where(cross == 0, -1, cross)  # already elevated when the window opened: not a cause
    dev = deviation_term(window, node_thr, cross, DEV_HORIZON)
    ons = onset_term(cross)
    cau = causal_term(graph, dev, names)
    score = weights.deviation * dev + weights.onset * ons + weights.causal * cau
    raw = score.copy()
    conf = softmax(score)
    types = types or [str(NODE_BY_ID[n].type) for n in names]
    idx = {n: k for k, n in enumerate(names)}
    static = [(u, v) for u, v, d in graph.edges(data=True) if d.get("kind") == "static"]
    # Reach follows the P&ID when there is one (learned edges are too dense on SIM); a plant
    # without a published P&ID (HAI) only has the learned, already sparse, edges.
    pid = nx.DiGraph(static or [(u, v) for u, v in graph.edges])
    pid.add_nodes_from(names)
    downstream = [{idx[d] for d in nx.descendants(pid, n) if d in idx} for n in names]
    ranked, score, conf = break_ties(score, conf, cross, types, downstream)
    return [
        Candidate(
            id=names[i],
            type=types[i],
            score=float(score[i]),
            confidence=float(conf[i]),
            deviation=float(dev[i]),
            onset_idx=int(cross[i]) if cross[i] >= 0 else None,
            causal=float(cau[i]),
            onset=float(ons[i]),
            raw_score=float(raw[i]),
            weights=weights,
        )
        for i in ranked
    ]
