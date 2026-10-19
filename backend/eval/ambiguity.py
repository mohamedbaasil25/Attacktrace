"""Confidence gate (Phase 11 B2): an incident is ambiguous when the top two candidates are close.

The margin is tuned on validation and tuning attacks only (seeds 300-307 and 400-419 per
scenario); the held-out test seeds (1000-1009) are scored once with the chosen margin.
"""

from dataclasses import dataclass

import networkx as nx
import numpy as np

from app.attacks import Scenario
from app.data.simdata import attack_run
from app.detect.pipeline import Loaded
from app.localize import Weights, build_incident
from eval.localization import TUNE_ATTACK_SEEDS, Scored, score_runs

VAL_ATTACK_SEEDS = range(300, 308)
TARGET_ACCURACY = 0.95  # fixed before looking at any data: Top-1 on non-ambiguous incidents
MARGINS = tuple(round(m * 0.01, 2) for m in range(0, 61))


@dataclass(frozen=True)
class Row:
    margin: float  # top-1 confidence minus top-2 confidence
    top1: bool
    top3: bool


def rows(loaded: Loaded, graph: nx.DiGraph, scored: list[Scored], w: Weights) -> list[Row]:
    """One row per detected attack (a missed attack opens no incident, so it has no margin)."""
    mu = loaded.detector.norm.mu
    out = []
    for s in scored:
        if s.alert_idx is None:
            continue
        assert s.run.truth is not None
        inc = build_incident(
            s.scores, s.errors, s.run.x, s.alert_idx, mu, loaded.node_thr, graph, w
        )
        ids = [c.id for c in inc.candidates]
        t = s.run.truth.target
        out.append(
            Row(
                inc.candidates[0].confidence - inc.candidates[1].confidence,
                ids[0] == t,
                t in ids[:3],
            )
        )
    return out


def summarize(rs: list[Row], margin: float) -> dict[str, object]:
    amb = [r for r in rs if r.margin < margin]
    sure = [r for r in rs if r.margin >= margin]
    return {
        "gate_margin": margin,
        "n_incidents": len(rs),
        "ambiguous_rate": len(amb) / len(rs) if rs else None,
        "n_ambiguous": len(amb),
        "n_non_ambiguous": len(sure),
        "top1_non_ambiguous": float(np.mean([r.top1 for r in sure])) if sure else None,
        "top1_ambiguous": float(np.mean([r.top1 for r in amb])) if amb else None,
        "top3_ambiguous": float(np.mean([r.top3 for r in amb])) if amb else None,
    }


def tune_margin(rs: list[Row]) -> float:
    """Smallest margin whose non-ambiguous incidents reach TARGET_ACCURACY; if none does, the
    margin with the best non-ambiguous accuracy among those flagging at most half the incidents."""
    for m in MARGINS:
        s = summarize(rs, m)
        acc = s["top1_non_ambiguous"]
        if acc is not None and float(acc) >= TARGET_ACCURACY:  # type: ignore[arg-type]
            return m
    ok = [m for m in MARGINS if float(summarize(rs, m)["ambiguous_rate"] or 0) <= 0.5]  # type: ignore[arg-type]
    return max(ok, key=lambda m: float(summarize(rs, m)["top1_non_ambiguous"] or 0))  # type: ignore[arg-type]


def tuning_rows(loaded: Loaded, graph: nx.DiGraph, w: Weights) -> list[Row]:
    runs = [attack_run(s, sc) for sc in Scenario for s in (*VAL_ATTACK_SEEDS, *TUNE_ATTACK_SEEDS)]
    return rows(loaded, graph, score_runs(loaded, runs), w)


if __name__ == "__main__":
    from app.config import get_settings
    from app.detect.pipeline import load_detector
    from app.graph import load_graph

    cfg = get_settings()
    ld, gr = load_detector(cfg.models_dir), load_graph(cfg.models_dir / "graph.json")
    wt = Weights(cfg.w_deviation, cfg.w_onset, cfg.w_causal)
    rs = tuning_rows(ld, gr, wt)
    print(len(rs), "tuning incidents")
    for m in (0.0, 0.02, 0.05, 0.08, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5):
        print(summarize(rs, m))
    print("chosen margin:", tune_margin(rs))
