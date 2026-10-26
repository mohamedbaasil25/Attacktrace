"""Phase 16 A9: explanation coverage (origin, path, action, MITRE ID present) for SIM, LIVE, HAI.

SIM: measured directly, read-only, over the 50 held-out test attacks (same frozen models/method as
A1's offline pipeline). LIVE: NOT measured -- `reports/live_metrics.json` per-attack records save
only `{scenario,target,detected,top1,top3,time_to_localize_s,detection_delay_s}`; no incident
object (origin/path/action/mitre) was ever saved for the LIVE eval, and re-running the ~2h53m
`eval.live` harness just to capture this is out of Part A's scope (no new runs). HAI: origin/path/
action are always populated by construction (`app/engine_hai.py:232-233`, no conditional empty
path); MITRE is a documented, intentional design gap, not a coverage defect --
`app/engine_hai.py:247`: `mitre=""  # HAI carries no ATT&CK labels; the UI hides empty tags`.
"""

from app.config import get_settings
from app.detect.pipeline import load_detector
from app.graph import load_graph
from app.localize import Weights, build_incident
from eval.analysis._util import merge_write_final
from eval.localization import score_runs, test_runs


def analyze() -> dict[str, object]:
    settings = get_settings()
    loaded = load_detector(settings.models_dir)
    graph = load_graph(settings.models_dir / "graph.json")
    weights = Weights(settings.w_deviation, settings.w_onset, settings.w_causal)

    runs = test_runs()
    scored = score_runs(loaded, runs)
    mu = loaded.detector.norm.mu

    n = len(runs)
    n_detected = 0
    missing: list[dict[str, object]] = []
    for r, s in zip(runs, scored, strict=True):
        assert r.truth is not None
        if s.alert_idx is None:
            continue
        n_detected += 1
        inc = build_incident(
            s.scores, s.errors, s.run.x, s.alert_idx, mu, loaded.node_thr, graph, weights
        )
        gaps = []
        if not inc.candidates:
            gaps.append("origin")
        if not inc.propagation.nodes:
            gaps.append("path")
        if not inc.explanation.action:
            gaps.append("action")
        if not inc.explanation.mitre:
            gaps.append("mitre")
        if gaps:
            missing.append({"scenario": r.truth.scenario.value, "missing": gaps})

    return {
        "sim": {
            "n_runs": n,
            "n_detected": n_detected,
            "n_with_all_four_fields": n_detected - len(missing),
            "coverage_fraction_of_detected": (n_detected - len(missing)) / n_detected
            if n_detected
            else None,
            "exceptions": missing,
        },
        "live": "Not measured: live_metrics.json per-attack records do not save the incident's "
        "origin/path/action/mitre, only detection/localization booleans and timings. Would need a "
        "fresh instrumented LIVE run (out of Part A's no-new-runs scope) to measure directly.",
        "hai": {
            "origin_path_action": "Always populated by construction, not sampled: "
            "app/engine_hai.py lines 232-233 build (origin, path, edges, text, action) from "
            "`reconstruct()`/`_analysis()` with no conditional branch that returns them empty.",
            "mitre": "Intentionally ALWAYS empty by design, not a coverage gap: "
            'app/engine_hai.py:247 `mitre=""  # HAI carries no ATT&CK labels; the UI hides empty '
            "tags`. The A9 expectation of '100% coverage incl. MITRE' does not apply to HAI; "
            "origin/path/action coverage is structurally 100% there, MITRE coverage is "
            "structurally 0% there, both by design.",
        },
    }


def main() -> int:
    result = analyze()
    out = merge_write_final("explanation_coverage", result)
    sim = result["sim"]
    assert isinstance(sim, dict)
    print(
        f"wrote {out}: SIM coverage={sim['coverage_fraction_of_detected']} "
        f"(n_detected={sim['n_detected']}, exceptions={len(sim['exceptions'])}) | "
        "LIVE not measured | HAI: origin/path/action always set, MITRE always empty by design"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
