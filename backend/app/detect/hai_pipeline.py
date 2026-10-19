"""Train, tune, persist and load the detectors for the HAI dataset (models live in models/hai/).

Protocol: the last 10% of train1 is clean validation (early stopping, error scale, onset
thresholds); `test2` tunes the alert threshold; the other test files are held out for `make eval`.
HAI has no published P&ID, so the graph is learned (`learn_var_edges`).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

import joblib
import networkx as nx
import numpy as np
import torch
from numpy.typing import NDArray

from app.data.hai import HaiData, HaiFile, load_hai, node_kind
from app.detect.baseline import BaselineDetector
from app.detect.detector import ForecastDetector, aggregate, best_threshold, fit_err_sd
from app.detect.forecaster import Norm, build_model, train
from app.graph import adjacency, learn_var_edges, learned_graph, load_graph, save_graph

F64 = NDArray[np.float64]

WINDOW = 10  # samples (10 s at 1 Hz)
TOP_K = 3  # nodes in the aggregate alert score (50 nodes: a little more than SIM's 2)
TRAIN_STRIDE = 3  # train on every 3rd window; neighbouring windows are nearly identical
VAL_FRACTION = 0.1
NODE_THR_QUANTILE = 0.999
SEED = 0
TRAIN_THREADS = 4
KINDS = ("gdn", "mlp")
# Delta form (last value + learned change) is robust to the level shifts between HAI recording
# days; the absolute form used for SIM treats any shift outside the training range as an anomaly.
RESIDUAL = True


@dataclass(frozen=True)
class HaiLoaded:
    detector: ForecastDetector
    threshold: float
    node_thr: F64
    features: tuple[str, ...]
    types: list[str]
    graph: nx.DiGraph
    kind: str


def split_tests(data: HaiData) -> tuple[HaiFile, list[HaiFile]]:
    """(tuning file, held-out files): the last test file tunes, the rest evaluate."""
    if len(data.tests) < 2:
        raise ValueError("HAI evaluation needs at least two test files (one to tune, one held out)")
    return data.tests[-1], data.tests[:-1]


def _windows(xn: F64, stride: int) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    starts = np.arange(0, len(xn) - WINDOW, stride)
    idx = starts[:, None] + np.arange(WINDOW)[None, :]
    return xn[idx].astype(np.float32), xn[starts + WINDOW].astype(np.float32)


def train_hai(
    models_dir: Path, hai_dir: Path, epochs: int = 12, log: bool = True
) -> dict[str, object]:
    out = models_dir / "hai"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    torch.set_num_threads(TRAIN_THREADS)
    data = load_hai(hai_dir)
    tune, _ = split_tests(data)
    names = tuple(data.features)
    types = [node_kind(c) for c in names]

    x_all = data.train_x
    cut = int(len(x_all) * (1 - VAL_FRACTION))
    x_tr, x_val = x_all[:cut], x_all[cut:]
    norm = Norm.fit(x_tr)
    graph = learned_graph(names, dict(zip(names, types, strict=True)), learn_var_edges(x_tr, names))
    save_graph(graph, out / "graph.json")
    adj = adjacency(graph, 0.0, names)

    train_xy = _windows(norm.apply(x_tr), TRAIN_STRIDE)
    val_xy = _windows(norm.apply(x_val), 1)
    base = BaselineDetector(names=names).fit(x_tr)
    joblib.dump(base, out / "baseline.joblib")

    results = []
    for kind in KINDS:
        torch.manual_seed(SEED)
        model = build_model(kind, len(names), WINDOW, adj, residual=RESIDUAL)
        t1 = time.time()
        mse = train(
            model,
            (train_xy[0].astype(np.float64), train_xy[1].astype(np.float64)),
            (val_xy[0].astype(np.float64), val_xy[1].astype(np.float64)),
            epochs=epochs,
        )
        det = ForecastDetector(
            model, norm, fit_err_sd(model, norm, [x_val], WINDOW), window=WINDOW, stuck_cols=[]
        )
        clean = aggregate(det.score_run(x_val), TOP_K)
        pairs = [
            (clean, np.zeros(len(clean), dtype=np.int8)),
            (aggregate(det.score_run(tune.x), TOP_K), tune.labels()),
        ]
        thr, f1 = best_threshold(pairs)
        node_thr = np.quantile(det.score_run(x_val)[WINDOW:], NODE_THR_QUANTILE, axis=0)
        results.append((kind, det, thr, f1, mse, node_thr))
        torch.save(model.state_dict(), out / f"{kind}.pt")
        if log:
            print(
                f"hai {kind}: val_mse={mse:.4f} tune_f1={f1:.3f} thr={thr:.3f} "
                f"({time.time() - t1:.0f}s)"
            )

    best = max(results, key=lambda r: r[3] + (0.02 if r[0] == "gdn" else 0.0))
    meta = {
        "active": best[0],
        "window": WINDOW,
        "residual": RESIDUAL,
        "top_k": TOP_K,
        "features": list(names),
        "types": types,
        "norm": {"mu": norm.mu.tolist(), "sd": norm.sd.tolist()},
        "models": {
            kind: {
                "threshold": thr,
                "tune_f1": f1,
                "val_mse": mse,
                "err_sd": det.err_sd.tolist(),
                "node_thr": node_thr.tolist(),
            }
            for kind, det, thr, f1, mse, node_thr in results
        },
        "train_seconds": time.time() - t0,
    }
    (out / "detector.json").write_text(json.dumps(meta, indent=1))
    return meta


def hai_models_ready(models_dir: Path) -> bool:
    return (models_dir / "hai" / "detector.json").exists()


def load_hai_detector(models_dir: Path, kind: str | None = None) -> HaiLoaded:
    d = models_dir / "hai"
    meta = json.loads((d / "detector.json").read_text())
    kind = kind or str(meta["active"])
    names = tuple(meta["features"])
    graph = load_graph(d / "graph.json")
    model = build_model(
        kind,
        len(names),
        int(meta["window"]),
        adjacency(graph, 0.0, names),
        residual=bool(meta.get("residual", False)),
    )
    model.load_state_dict(torch.load(d / f"{kind}.pt"))
    norm = Norm(np.array(meta["norm"]["mu"]), np.array(meta["norm"]["sd"]))
    m = meta["models"][kind]
    det = ForecastDetector(
        model, norm, np.array(m["err_sd"]), window=int(meta["window"]), stuck_cols=[]
    )
    return HaiLoaded(
        det, float(m["threshold"]), np.array(m["node_thr"]), names, list(meta["types"]), graph, kind
    )


def load_hai_baseline(models_dir: Path) -> BaselineDetector:
    base: BaselineDetector = joblib.load(models_dir / "hai" / "baseline.joblib")
    return base
