"""Train, tune, persist and load the detectors. `python -m app.detect.pipeline` trains."""

import json
import time
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import torch
from numpy.typing import NDArray

from app.attacks import Scenario
from app.config import get_settings
from app.data.simdata import Run, attack_run, simulate
from app.detect.baseline import BaselineDetector
from app.detect.detector import ForecastDetector, aggregate, best_threshold, fit_err_sd
from app.detect.forecaster import WINDOW, Norm, build_model, make_windows, train
from app.graph import adjacency, learn_granger_edges, load_graph, merge_graph, save_graph
from app.sim import NODE_IDS

F64 = NDArray[np.float64]

# Disjoint seed ranges: train / validation / test never share a plant seed.
TRAIN_SEEDS = range(100, 130)  # 30 clean runs of 600 s
VAL_CLEAN_SEEDS = range(200, 206)
VAL_ATTACK_SEEDS = range(300, 308)  # per scenario
GRAPH_SEED = 500
LEARNED_MIN_WEIGHT = 0.25  # learned edges below this stay out of the attention mask
NODE_THR_QUANTILE = 0.999
SEED = 0
TRAIN_THREADS = 4  # fixed so float summation order, and so the trained weights, never vary
KINDS = ("gdn", "mlp")


@dataclass(frozen=True)
class Loaded:
    detector: ForecastDetector
    threshold: float  # alert threshold on the top-k aggregate score
    node_thr: F64  # per-node score above which a node counts as deviating (onset detection)


@dataclass
class Trained:
    kind: str
    detector: ForecastDetector
    threshold: float
    val_f1: float
    val_mse: float
    node_thr: F64


def _val_runs() -> tuple[list[Run], list[Run]]:
    clean = [simulate(s) for s in VAL_CLEAN_SEEDS]
    attacks = [attack_run(s, sc) for sc in Scenario for s in VAL_ATTACK_SEEDS]
    return clean, attacks


def train_all(models_dir: Path, epochs: int = 40, log: bool = True) -> dict[str, object]:
    models_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    torch.set_num_threads(TRAIN_THREADS)  # thread-local: also correct inside a worker thread
    x_train = np.vstack([simulate(s, 600.0).x for s in TRAIN_SEEDS])
    norm = Norm.fit(x_train)
    clean_val, attack_val = _val_runs()

    graph = merge_graph(learn_granger_edges(simulate(GRAPH_SEED, 900.0).x))
    save_graph(graph, models_dir / "graph.json")
    adj = adjacency(graph, LEARNED_MIN_WEIGHT)

    tx = [make_windows(norm.apply(simulate(s, 600.0).x)) for s in TRAIN_SEEDS]
    train_xy = (np.concatenate([a for a, _ in tx]), np.concatenate([b for _, b in tx]))
    vx = [make_windows(norm.apply(r.x)) for r in clean_val]
    val_xy = (np.concatenate([a for a, _ in vx]), np.concatenate([b for _, b in vx]))

    base = BaselineDetector().fit(x_train)
    joblib.dump(base, models_dir / "baseline.joblib")

    results: list[Trained] = []
    for kind in KINDS:
        torch.manual_seed(SEED)  # weight init, independent of what ran before
        model = build_model(kind, len(NODE_IDS), WINDOW, adj)
        t1 = time.time()
        mse = train(model, train_xy, val_xy, epochs=epochs)
        err_sd = fit_err_sd(model, norm, [r.x for r in clean_val])
        det = ForecastDetector(model, norm, err_sd)
        pairs = [(aggregate(det.score_run(r.x)), r.labels()) for r in clean_val + attack_val]
        thr, f1 = best_threshold(pairs)
        clean_scores = np.vstack([det.score_run(r.x)[WINDOW:] for r in clean_val])
        node_thr = np.quantile(clean_scores, NODE_THR_QUANTILE, axis=0)
        results.append(Trained(kind, det, thr, f1, mse, node_thr))
        torch.save(model.state_dict(), models_dir / f"{kind}.pt")
        if log:
            print(
                f"{kind}: val_mse={mse:.4f} val_f1={f1:.3f} thr={thr:.3f} ({time.time() - t1:.0f}s)"
            )

    # GDN is primary; the MLP fallback takes over only if it clearly beats it on validation.
    active = max(results, key=lambda r: r.val_f1 + (0.02 if r.kind == "gdn" else 0.0))
    meta = {
        "active": active.kind,
        "window": WINDOW,
        "learned_min_weight": LEARNED_MIN_WEIGHT,
        "norm": {"mu": norm.mu.tolist(), "sd": norm.sd.tolist()},
        "models": {
            r.kind: {
                "threshold": r.threshold,
                "val_f1": r.val_f1,
                "val_mse": r.val_mse,
                "err_sd": r.detector.err_sd.tolist(),
                "node_thr": r.node_thr.tolist(),
            }
            for r in results
        },
        "train_seconds": time.time() - t0,
    }
    (models_dir / "detector.json").write_text(json.dumps(meta, indent=1))
    return meta


def load_detector(models_dir: Path, kind: str | None = None) -> Loaded:
    """Load a trained detector (default: the active one) with its thresholds."""
    meta = json.loads((models_dir / "detector.json").read_text())
    kind = kind or str(meta["active"])
    graph = load_graph(models_dir / "graph.json")
    adj = adjacency(graph, float(meta["learned_min_weight"]))
    model = build_model(kind, len(NODE_IDS), int(meta["window"]), adj)
    model.load_state_dict(torch.load(models_dir / f"{kind}.pt"))
    norm = Norm(np.array(meta["norm"]["mu"]), np.array(meta["norm"]["sd"]))
    m = meta["models"][kind]
    det = ForecastDetector(model, norm, np.array(m["err_sd"]))
    return Loaded(det, float(m["threshold"]), np.array(m["node_thr"]))


def load_baseline(models_dir: Path) -> BaselineDetector:
    base: BaselineDetector = joblib.load(models_dir / "baseline.joblib")
    return base


if __name__ == "__main__":
    out = train_all(get_settings().models_dir)
    print(f"active={out['active']}")
