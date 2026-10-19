"""Localization evaluation: Top-1 / Top-3 origin accuracy and time-to-localize on SIM attacks."""

from dataclasses import dataclass

import networkx as nx
import numpy as np
from numpy.typing import NDArray

from app.attacks import Scenario
from app.data.simdata import Run, attack_run
from app.detect.baseline import SIGMA, BaselineDetector
from app.detect.detector import aggregate, alert_mask, rising_edges
from app.detect.pipeline import Loaded
from app.localize import Weights, build_incident
from app.localize.incident import FORWARD_S, LOOKBACK_S, SAMPLE_DT
from app.localize.locator import softmax
from app.sim import NODE_IDS

F64 = NDArray[np.float64]

TEST_ATTACK_SEEDS = range(1000, 1010)  # same held-out attacks as detection eval
TUNE_ATTACK_SEEDS = range(400, 420)  # per scenario; used only to pick localization weights


@dataclass(frozen=True)
class Scored:
    run: Run
    scores: F64
    errors: F64
    alert_idx: int | None  # first new alert after the attack start (false alarms: see detection)


def score_runs(loaded: Loaded, runs: list[Run]) -> list[Scored]:
    out = []
    for r in runs:
        assert r.truth is not None
        scores = loaded.detector.score_run(r.x)
        errors = loaded.detector.errors(r.x)
        alert = alert_mask(aggregate(scores), loaded.threshold)
        # An alert already running when the attack starts is a stale false alarm: the incident
        # that matters opens on the next rising edge.
        edges = rising_edges(alert)
        edges = edges[r.t[edges] >= r.truth.start_s]
        out.append(Scored(r, scores, errors, int(edges[0]) if edges.size else None))
    return out


def evaluate_localization(
    loaded: Loaded, graph: nx.DiGraph, scored: list[Scored], weights: Weights
) -> dict[str, object]:
    mu = loaded.detector.norm.mu
    per: dict[str, list[tuple[bool, bool]]] = {sc.value: [] for sc in Scenario}
    ttl: list[float] = []
    for s in scored:
        assert s.run.truth is not None
        key = s.run.truth.scenario.value
        if s.alert_idx is None:
            per[key].append((False, False))
            continue
        inc = build_incident(
            s.scores, s.errors, s.run.x, s.alert_idx, mu, loaded.node_thr, graph, weights
        )
        ranked = [c.id for c in inc.candidates]
        target = s.run.truth.target
        per[key].append((ranked[0] == target, target in ranked[:3]))
        ttl.append(float(s.run.t[s.alert_idx]) + FORWARD_S - s.run.truth.start_s)
    flat = [v for vs in per.values() for v in vs]
    return {
        "top1": float(np.mean([a for a, _ in flat])),
        "top3": float(np.mean([b for _, b in flat])),
        "mean_time_to_localize_s": float(np.mean(ttl)) if ttl else None,
        "per_scenario": {
            k: {
                "top1": float(np.mean([a for a, _ in v])),
                "top3": float(np.mean([b for _, b in v])),
            }
            for k, v in per.items()
        },
        "n_runs": len(flat),
        "weights": {
            "deviation": weights.deviation,
            "onset": weights.onset,
            "causal": weights.causal,
        },
        "window": {"lookback_s": 40.0, "forward_s": FORWARD_S, "dt": SAMPLE_DT},
    }


def baseline_rank(base: BaselineDetector, x: F64, alert_idx: int) -> list[str]:
    """What an operator reading the baseline's alarms would guess: nodes ordered by the first
    3-sigma breach in the incident window, ties broken by the larger deviation."""
    lo = max(0, alert_idx - round(LOOKBACK_S / SAMPLE_DT))
    hi = min(len(x), alert_idx + round(FORWARD_S / SAMPLE_DT) + 1)
    z = base.zscores(x[lo:hi])
    breach = z > SIGMA
    first = np.where(breach.any(axis=0), breach.argmax(axis=0), len(z))
    peak = z.max(axis=0)
    order = sorted(range(len(NODE_IDS)), key=lambda i: (first[i], -peak[i]))
    return [NODE_IDS[i] for i in order]


def evaluate_baseline_localization(base: BaselineDetector, runs: list[Run]) -> dict[str, object]:
    """Top-1 / Top-3 for the baseline under the same protocol as AttackTrace: the incident
    opens on its first alert after the attack starts; a missed attack counts as a miss."""
    per: dict[str, list[tuple[bool, bool]]] = {sc.value: [] for sc in Scenario}
    for r in runs:
        assert r.truth is not None
        edges = rising_edges(base.alert(r.x))
        edges = edges[r.t[edges] >= r.truth.start_s]
        key = r.truth.scenario.value
        if not edges.size:
            per[key].append((False, False))
            continue
        ranked = baseline_rank(base, r.x, int(edges[0]))
        per[key].append((ranked[0] == r.truth.target, r.truth.target in ranked[:3]))
    flat = [v for vs in per.values() for v in vs]
    return {
        "top1": float(np.mean([a for a, _ in flat])),
        "top3": float(np.mean([b for _, b in flat])),
        "per_scenario": {
            k: {
                "top1": float(np.mean([a for a, _ in v])),
                "top3": float(np.mean([b for _, b in v])),
            }
            for k, v in per.items()
            if v
        },
        "n_runs": len(flat),
    }


def test_runs() -> list[Run]:
    return [attack_run(s, sc) for sc in Scenario for s in TEST_ATTACK_SEEDS]


def tune_weights(
    loaded: Loaded, graph: nx.DiGraph, step: float = 0.1, floor: float = 0.2
) -> Weights:
    """Grid search over weights (each >= floor, summing to 1) maximizing Top-1 + Top-3. The
    floor keeps all three evidence terms in play instead of letting one dominate."""
    runs = [attack_run(s, sc) for sc in Scenario for s in TUNE_ATTACK_SEEDS]
    scored = score_runs(loaded, runs)
    k = round(1 / step)
    best, best_w = -1.0, Weights()
    lo = round(floor / step)
    for a in range(lo, k - 2 * lo + 1):
        for b in range(lo, k - a - lo + 1):
            w = Weights(a * step, b * step, (k - a - b) * step)
            r = evaluate_localization(loaded, graph, scored, w)
            obj = float(r["top1"]) + float(r["top3"])  # type: ignore[arg-type]
            if obj > best:
                best, best_w = obj, w
    return best_w


def calibrate_temperature(
    loaded: Loaded, graph: nx.DiGraph, weights: Weights, grid: int = 60
) -> tuple[float, float, float]:
    """Softmax temperature minimizing the log-loss of the true origin on the tuning attacks.
    Returns (temperature, nll, mean top-1 confidence)."""
    runs = [attack_run(s, sc) for sc in Scenario for s in TUNE_ATTACK_SEEDS]
    mu = loaded.detector.norm.mu
    rows: list[tuple[np.ndarray, int]] = []
    for s in score_runs(loaded, runs):
        if s.alert_idx is None:
            continue
        assert s.run.truth is not None
        inc = build_incident(
            s.scores, s.errors, s.run.x, s.alert_idx, mu, loaded.node_thr, graph, weights
        )
        ids = [c.id for c in inc.candidates]
        rows.append((np.array([c.score for c in inc.candidates]), ids.index(s.run.truth.target)))
    best = (0.0, float("inf"), 0.0)
    for temp in np.geomspace(0.02, 1.0, grid):
        nll, top = 0.0, 0.0
        for sc, k in rows:
            p = softmax(sc, float(temp))
            nll -= float(np.log(max(p[k], 1e-12)))
            top += float(p[0])
        if nll / len(rows) < best[1]:
            best = (float(temp), nll / len(rows), top / len(rows))
    return best


if __name__ == "__main__":
    from app.config import get_settings
    from app.detect.pipeline import load_detector
    from app.graph import load_graph

    cfg = get_settings()
    ld, gr = load_detector(cfg.models_dir), load_graph(cfg.models_dir / "graph.json")
    w = Weights(cfg.w_deviation, cfg.w_onset, cfg.w_causal)
    print("tuned weights:", tune_weights(ld, gr))
    print("temperature (temp, nll, mean top-1 confidence):", calibrate_temperature(ld, gr, w))
