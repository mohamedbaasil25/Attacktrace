"""Phase 11 B5: time-boxed attempt to raise HAI strict F1 (at most two experiments).

Experiment 1: minimum alert duration (persistence). Experiment 2: EWMA smoothing. Every variant
re-picks its threshold on the TUNING day (`test2`) plus the clean validation tail of `train1`
only. The held-out file (`test1`) is not read here; it is scored once, afterwards, for a variant
that beat the current setting by at least MIN_GAIN on the tuning day (fixed before looking).
"""

import json
import sys

import numpy as np
from numpy.typing import NDArray
from scipy.signal import lfilter

from app.config import get_settings
from app.data.hai import load_hai
from app.detect.detector import PERSIST, aggregate, alert_mask
from app.detect.hai_pipeline import TOP_K, VAL_FRACTION, load_hai_detector, split_tests

F64 = NDArray[np.float64]
MIN_GAIN = 0.02  # tuning-day strict F1 gain required before the held-out file is touched
PERSISTS = (3, 10, 20, 40)  # experiment 1 (3 = current)
ALPHAS = (0.25, 0.1, 0.05)  # experiment 2 (0.25 = current)


def smooth(err: F64, alpha: float) -> F64:
    return np.asarray(lfilter([alpha], [1.0, -(1.0 - alpha)], err, axis=0))


def best_f1(
    pairs: list[tuple[F64, NDArray[np.int8]]], persist: int, grid: int = 200
) -> tuple[float, float]:
    agg = np.concatenate([a[y >= 0] for a, y in pairs])
    lab = np.concatenate([y[y >= 0] for _, y in pairs])
    best = (0.0, -1.0)
    for thr in np.quantile(agg, np.linspace(0.5, 0.999, grid)):
        pred = np.concatenate([alert_mask(a, float(thr), persist)[y >= 0] for a, y in pairs])
        tp = int(np.sum(pred & (lab == 1)))
        fp = int(np.sum(pred & (lab == 0)))
        fn = int(np.sum(~pred & (lab == 1)))
        f1 = 2 * tp / max(2 * tp + fp + fn, 1)
        if f1 > best[1]:
            best = (float(thr), f1)
    return best


def main() -> int:
    cfg = get_settings()
    data = load_hai(cfg.hai_dir)
    tune, _ = split_tests(data)  # the held-out files are deliberately not used below
    loaded = load_hai_detector(cfg.models_dir)
    x_all = data.train_x
    x_val = x_all[int(len(x_all) * (1 - (VAL_FRACTION))) :]
    e_val, e_tune = loaded.detector.errors(x_val), loaded.detector.errors(tune.x)
    y_val = np.zeros(len(e_val), dtype=np.int8)
    y_tune = tune.labels()

    def score(alpha: float, persist: int) -> dict[str, float]:
        pairs = [
            (aggregate(smooth(e_val, alpha), TOP_K), y_val),
            (aggregate(smooth(e_tune, alpha), TOP_K), y_tune),
        ]
        thr, f1 = best_f1(pairs, persist)
        return {"alpha": alpha, "persist": persist, "threshold": thr, "tune_f1": f1}

    current = score(loaded.detector.alpha, PERSIST)
    print("current", current, " (stored tune_f1 from training:", end=" ")
    meta = json.loads((cfg.models_dir / "hai" / "detector.json").read_text())
    print(meta["models"][meta["active"]]["tune_f1"], ")")
    exp1 = [score(loaded.detector.alpha, p) for p in PERSISTS]
    exp2 = [score(a, PERSIST) for a in ALPHAS]
    for name, rows in (("experiment 1: min duration", exp1), ("experiment 2: smoothing", exp2)):
        print(name)
        for r in rows:
            print("  ", r)
    cand = max([*exp1, *exp2], key=lambda r: r["tune_f1"])
    gain = cand["tune_f1"] - current["tune_f1"]
    print(f"best variant {cand}; tuning-day gain {gain:+.3f} (bar {MIN_GAIN})")
    result: dict[str, object] = {"current": current, "experiment_1": exp1, "experiment_2": exp2}
    result |= {"best": cand, "tuning_gain": gain, "min_gain": MIN_GAIN, "held_out_scored": False}
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
