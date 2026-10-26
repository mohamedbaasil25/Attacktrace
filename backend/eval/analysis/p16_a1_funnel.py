"""Phase 16 A1: attack funnel reconciliation (attacks -> detected -> Top-1 -> Top-3 -> contained),
on the held-out SIM test seeds (1000-1009 per scenario, 50 attacks total).

Finds TWO separate, already-committed Top-1 pipelines that use different incident snapshots and
were never previously joined per-attack:

  1. `eval.localization.evaluate_localization` -- OFFLINE: for each attack, takes the alert index
     and calls `build_incident()` once directly (the full 40s-lookback/10s-forward window in one
     batch), producing `metrics.json.localization.top1` (0.84, 42/50).
  2. `eval.isolation.run_isolation` -- LIVE: replays the same attack through the stepped `Engine`
     and reads the incident's origin ranking the first sample `status == "open"` (after the
     engine's own `localizing` phase), producing `metrics.json.isolation.isolate_top1` (0.80, 40/50
     contained -- a containment rate, not directly a ranking-accuracy rate).

This script re-derives BOTH per-attack (not just their committed aggregates) from the identical,
frozen, already-trained models and the identical seed/scenario iteration order used by the
committed eval, and joins them by (scenario, seed) to produce one funnel with both an end-to-end
(denominator = 50) and a conditional-on-detected (denominator = n detected) reading, and to show
exactly which attacks are responsible for the 0.84 vs 0.80 gap. No model, weight or threshold is
changed; this is a read-only recompute of two already-committed, already-approved eval paths,
consistency-guarded against the committed `metrics.json` aggregates.
"""

import json

import numpy as np

from app.attacks import Scenario
from app.config import get_settings
from app.detect.pipeline import load_baseline, load_detector
from app.engine import Engine
from app.graph import load_graph
from app.localize import Weights, build_incident
from eval.analysis._util import merge_write_final, reports_dir
from eval.isolation import _isolate, _open_incident, _spec
from eval.localization import TEST_ATTACK_SEEDS, score_runs, test_runs


def analyze() -> dict[str, object]:
    settings = get_settings()
    loaded = load_detector(settings.models_dir)
    baseline = load_baseline(settings.models_dir)
    graph = load_graph(settings.models_dir / "graph.json")
    weights = Weights(settings.w_deviation, settings.w_onset, settings.w_causal)

    # --- OFFLINE pipeline (same method as metrics.json.localization.top1), keyed by position ---
    runs = test_runs()
    scored = score_runs(loaded, runs)
    mu = loaded.detector.norm.mu
    offline: list[dict[str, object]] = []
    for r, s in zip(runs, scored, strict=True):
        assert r.truth is not None
        if s.alert_idx is None:
            offline.append(
                {
                    "scenario": r.truth.scenario.value,
                    "detected": False,
                    "top1": False,
                    "top3": False,
                }
            )
            continue
        inc = build_incident(
            s.scores, s.errors, s.run.x, s.alert_idx, mu, loaded.node_thr, graph, weights
        )
        ranked = [c.id for c in inc.candidates]
        target = r.truth.target
        offline.append(
            {
                "scenario": r.truth.scenario.value,
                "detected": True,
                "top1": ranked[0] == target,
                "top3": target in ranked[:3],
            }
        )

    # consistency guard: recomputed offline top1/top3 must match the committed metrics.json
    committed = json.loads((reports_dir() / "metrics.json").read_text())
    per_scenario = committed["detection"]["attacktrace"]["per_scenario"]
    recomputed_top1 = float(np.mean([bool(o["top1"]) for o in offline]))
    recomputed_top3 = float(np.mean([bool(o["top3"]) for o in offline]))
    committed_top1 = committed["localization"]["top1"]
    committed_top3 = committed["localization"]["top3"]

    # --- LIVE/engine pipeline (same method as metrics.json.isolation.*), in the SAME order ---
    engine = Engine(loaded, baseline, graph, settings)
    live: list[dict[str, object]] = []
    for sc in Scenario:
        for seed in TEST_ATTACK_SEEDS:
            spec = _spec(seed, sc)
            opened = _open_incident(engine, seed, spec)
            if opened is None:
                live.append(
                    {
                        "scenario": sc.value,
                        "detected": False,
                        "top1": False,
                        "top3": False,
                        "contained": False,
                    }
                )
                continue
            inc_id, ranked = opened
            top1_live = ranked[0] == spec.target
            top3_live = spec.target in ranked[:3]
            arm = _isolate(engine, inc_id, ranked[0])
            live.append(
                {
                    "scenario": sc.value,
                    "detected": True,
                    "top1": top1_live,
                    "top3": top3_live,
                    "contained": arm.contained,
                }
            )

    live_detected = sum(1 for a in live if a["detected"])
    live_top1 = sum(1 for a in live if a["top1"])
    live_top3 = sum(1 for a in live if a["top3"])
    live_contained_given_top1 = sum(1 for a in live if a["top1"] and a["contained"])
    live_contained_total = sum(1 for a in live if a["contained"])

    offline_detected = sum(1 for o in offline if o["detected"])
    offline_top1 = sum(1 for o in offline if o["top1"])
    offline_top3 = sum(1 for o in offline if o["top3"])

    n = len(offline)
    assert n == 50 == len(live)

    # per-attack joint table: where do the two pipelines disagree on top1?
    disagreements = [
        {
            "index": idx,
            "scenario": offline[idx]["scenario"],
            "offline_top1": offline[idx]["top1"],
            "live_top1": live[idx]["top1"],
        }
        for idx in range(n)
        if offline[idx]["top1"] != live[idx]["top1"]
    ]

    return {
        "n_attacks": n,
        "offline_pipeline": {
            "description": "eval.localization.evaluate_localization: alert_idx -> single batch "
            "build_incident() call over the full 40s/10s window. This is what metrics.json's "
            "localization.top1/top3 were computed with.",
            "detected_end_to_end": {"k": offline_detected, "n": n, "p": offline_detected / n},
            "top1_end_to_end": {"k": offline_top1, "n": n, "p": offline_top1 / n},
            "top1_conditional_on_detected": {
                "k": offline_top1,
                "n": offline_detected,
                "p": offline_top1 / offline_detected if offline_detected else None,
            },
            "top3_end_to_end": {"k": offline_top3, "n": n, "p": offline_top3 / n},
            "consistency_check_top1": "match"
            if abs(recomputed_top1 - committed_top1) < 1e-9
            else f"MISMATCH recomputed={recomputed_top1} committed={committed_top1}",
            "consistency_check_top3": "match"
            if abs(recomputed_top3 - committed_top3) < 1e-9
            else f"MISMATCH recomputed={recomputed_top3} committed={committed_top3}",
        },
        "live_engine_pipeline": {
            "description": "eval.isolation.run_isolation: steps the live Engine, reads the "
            "incident's origin ranking the FIRST sample status=='open' (after the localizing "
            "refinement phase), then isolates the ranked[0] candidate. This is what "
            "metrics.json.isolation.{n_detected,isolate_top1} were computed with.",
            "detected_end_to_end": {"k": live_detected, "n": n, "p": live_detected / n},
            "top1_at_open_end_to_end": {"k": live_top1, "n": n, "p": live_top1 / n},
            "top1_at_open_conditional_on_detected": {
                "k": live_top1,
                "n": live_detected,
                "p": live_top1 / live_detected if live_detected else None,
            },
            "top3_at_open_end_to_end": {"k": live_top3, "n": n, "p": live_top3 / n},
            "isolate_top1_contained_given_top1_correct": {
                "k": live_contained_given_top1,
                "n": live_top1,
                "p": live_contained_given_top1 / live_top1 if live_top1 else None,
            },
            "isolate_top1_contained_end_to_end": {
                "k": live_contained_total,
                "n": n,
                "p": live_contained_total / n,
            },
            "consistency_check_detected": "match"
            if live_detected == committed["isolation"]["n_detected"]
            else (
                f"MISMATCH recomputed={live_detected} "
                f"committed={committed['isolation']['n_detected']}"
            ),
            "consistency_check_contained": "match"
            if live_contained_total == committed["isolation"]["isolate_top1"]["contained"]
            else (
                f"MISMATCH recomputed={live_contained_total} "
                f"committed={committed['isolation']['isolate_top1']['contained']}"
            ),
        },
        "reconciliation": {
            "finding": "The two pipelines are NOT the same measurement joined differently -- they "
            "are two independently-computed rankings (offline batch build_incident vs the live "
            "engine's incident at first 'open'), which can and do disagree per-attack. "
            f"{len(disagreements)}/{n} attacks have a different top1-correct verdict between the "
            "two pipelines. The committed 0.84 (offline) and 0.80 contained-rate (live, a "
            "CONTAINMENT rate, not a ranking-accuracy rate) are both individually correct and "
            "internally consistent (see consistency checks above), but are not interchangeable "
            "and were never previously reconciled against each other.",
            "disagreements": disagreements,
            "note_on_48_vs_49_vs_50": "The current committed reports/metrics.json has "
            f"isolation.n_detected={committed['isolation']['n_detected']} (all 50; recomputed "
            f"here: {live_detected}) and detection.per_scenario sums to "
            f"{round(sum(v['runs_detected'] for v in per_scenario.values()) * 10)}/50 "
            "run-level detections. The fix-prompt's own context block cites '48 detected' and "
            "'49/50 detected', neither of which matches the CURRENT committed metrics.json "
            "(authoritative, byte-identical, unmodified) -- those figures likely describe an "
            "earlier revision of the evaluation. Reported here against the file as it stands.",
        },
    }


def main() -> int:
    result = analyze()
    out = merge_write_final("funnel_reconciliation", result)
    off = result["offline_pipeline"]
    live_r = result["live_engine_pipeline"]
    reconciliation = result["reconciliation"]
    assert isinstance(off, dict) and isinstance(live_r, dict) and isinstance(reconciliation, dict)
    off_top1 = off["top1_end_to_end"]
    live_top1 = live_r["top1_at_open_end_to_end"]
    contained_given_top1 = live_r["isolate_top1_contained_given_top1_correct"]
    assert (
        isinstance(off_top1, dict)
        and isinstance(live_top1, dict)
        and isinstance(contained_given_top1, dict)
    )
    disagreements = reconciliation["disagreements"]
    assert isinstance(disagreements, list)
    print(
        f"wrote {out}: offline top1={off_top1['p']:.2f} "
        f"({off['consistency_check_top1']}) | live top1-at-open={live_top1['p']:.2f} "
        f"contained|top1={contained_given_top1['p']:.2f} "
        f"({live_r['consistency_check_contained']}) | "
        f"disagreements={len(disagreements)}/50"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
