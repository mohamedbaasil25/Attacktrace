"""Streaming detector: forecast error → per-node EWMA deviation score → top-k alert."""

from collections import deque
from collections.abc import Sequence

import numpy as np
import torch
from numpy.typing import NDArray
from scipy.signal import lfilter
from torch import nn

from app.detect.forecaster import WINDOW, Norm, predict
from app.sim import NODE_IDS
from app.sim.topology import SENSORS

F64 = NDArray[np.float64]

EWMA_ALPHA = 0.25
TOP_K = 2
FLAT_WIN = 6  # samples (3 s) a sensor must be exactly constant to count as stuck
FLAT_ERR = 8.0  # normalized error assigned to a stuck sensor (well above any clean error)
SENSOR_COLS = [NODE_IDS.index(n) for n in SENSORS]
PERSIST = 3  # consecutive samples above threshold before an alert fires
CHUNK = 16384  # windows predicted per batch, so a 300k-sample file never builds one huge array


def sustained(mask: NDArray[np.bool_], n: int = PERSIST) -> NDArray[np.bool_]:
    """True where `mask` has held for the last n samples (suppresses single-sample blips)."""
    idx = np.arange(len(mask))
    last_false = np.maximum.accumulate(np.where(mask, -1, idx))  # index of the latest False
    return np.asarray(mask & (idx - last_false >= n))


def rising_edges(mask: NDArray[np.bool_]) -> NDArray[np.int64]:
    """Sample indices where an alert starts (False → True); an alert already running at
    sample 0 counts as starting there."""
    prev = np.concatenate([[False], mask[:-1]])
    return np.flatnonzero(mask & ~prev).astype(np.int64)


def alert_mask(agg: F64, thr: float, n: int = PERSIST) -> NDArray[np.bool_]:
    return sustained(agg > thr, n)


def aggregate(scores: F64, k: int = TOP_K) -> F64:
    """Mean of the k largest node scores along the last axis."""
    return np.asarray(np.sort(scores, axis=-1)[..., -k:].mean(axis=-1), dtype=np.float64)


def best_threshold(
    pairs: list[tuple[F64, NDArray[np.int8]]], grid: int = 200
) -> tuple[float, float]:
    """Threshold on aggregate scores maximizing pooled sample-level F1 of the sustained alert
    (labels -1 ignored)."""
    agg = np.concatenate([a[y >= 0] for a, y in pairs])
    lab = np.concatenate([y[y >= 0] for _, y in pairs])
    best_thr, best_f1 = 0.0, -1.0
    for thr in np.quantile(agg, np.linspace(0.5, 0.999, grid)):
        pred = np.concatenate([alert_mask(a, float(thr))[y >= 0] for a, y in pairs])
        tp = int(np.sum(pred & (lab == 1)))
        fp = int(np.sum(pred & (lab == 0)))
        fn = int(np.sum(~pred & (lab == 1)))
        f1 = 2 * tp / max(2 * tp + fp + fn, 1)
        if f1 > best_f1:
            best_thr, best_f1 = float(thr), f1
    return best_thr, best_f1


def residuals(model: nn.Module, xn: F64, window: int = WINDOW, chunk: int = CHUNK) -> F64:
    """(T-window, N) signed one-step forecast error, predicted in chunks."""
    out = np.empty((len(xn) - window, xn.shape[1]))
    for s in range(0, len(out), chunk):
        e = min(s + chunk, len(out))
        idx = np.arange(s, e)[:, None] + np.arange(window)[None, :]
        out[s:e] = xn[window + s : window + e] - predict(model, xn[idx])
    return out


class ForecastDetector:
    def __init__(
        self,
        model: nn.Module,
        norm: Norm,
        err_sd: F64,
        alpha: float = EWMA_ALPHA,
        window: int = WINDOW,
        stuck_cols: Sequence[int] | None = None,
    ) -> None:
        """`stuck_cols`: columns checked for a frozen reading. Default is the SIM sensors; pass
        [] for data whose sensors can legitimately sit still (HAI)."""
        self.model, self.norm, self.err_sd = model, norm, err_sd
        self.alpha, self.window = alpha, window
        self.stuck_cols = list(SENSOR_COLS if stuck_cols is None else stuck_cols)
        self.reset()

    # ------------------------------------------------------------------ batch
    def errors(self, x: F64) -> F64:
        """(T, N) normalized absolute forecast error; zero for the first `window` samples."""
        xn = self.norm.apply(x)
        err = np.abs(residuals(self.model, xn, self.window)) / self.err_sd
        err = np.vstack([np.zeros((self.window, x.shape[1])), err])
        cols = self.stuck_cols
        for t in range(self.window, len(xn) if cols else 0):  # stuck-at check (SIM sensors)
            stuck = np.ptp(xn[t - FLAT_WIN + 1 : t + 1, cols], axis=0) == 0.0
            err[t, cols] = np.where(stuck, np.maximum(err[t, cols], FLAT_ERR), err[t, cols])
        return err

    def score_run(self, x: F64) -> F64:
        """(T, N) EWMA-smoothed deviation scores."""
        e = self.errors(x)
        return np.asarray(lfilter([self.alpha], [1.0, -(1.0 - self.alpha)], e, axis=0))

    # -------------------------------------------------------------- streaming
    def predict_next(self) -> F64 | None:
        """The model's expectation for the next raw sample, or None until the window is full."""
        if len(self._buf) < self.window:
            return None
        pred = predict(self.model, np.asarray(self._buf)[None])[0]
        return np.asarray(pred * self.norm.sd + self.norm.mu, dtype=np.float64)

    def reset(self) -> None:
        self._buf: deque[F64] = deque(maxlen=self.window)
        self._ewma: F64 | None = None
        self.last_error: F64 = np.zeros(len(self.err_sd))

    def update(self, x_t: F64) -> F64:
        """Feed one raw sample (N,); returns the current per-node scores (N,)."""
        xn = self.norm.apply(x_t)
        err = np.zeros_like(xn)
        if len(self._buf) == self.window:
            pred = predict(self.model, np.asarray(self._buf)[None])[0]
            err = np.abs(xn - pred) / self.err_sd
            cols = self.stuck_cols
            if cols:
                recent = np.asarray([*list(self._buf)[-(FLAT_WIN - 1) :], xn])[:, cols]
                stuck = np.ptp(recent, axis=0) == 0.0
                err[cols] = np.where(stuck, np.maximum(err[cols], FLAT_ERR), err[cols])
        self._buf.append(xn)
        self.last_error = err
        prev = np.zeros_like(err) if self._ewma is None else self._ewma
        self._ewma = self.alpha * err + (1.0 - self.alpha) * prev
        return self._ewma.copy()


def fit_err_sd(model: nn.Module, norm: Norm, clean: list[F64], window: int = WINDOW) -> F64:
    """Per-node std of the signed one-step forecast error on clean validation runs."""
    errs = [residuals(model, norm.apply(x), window) for x in clean]
    return np.asarray(np.maximum(np.concatenate(errs).std(axis=0), 1e-6), dtype=np.float64)


torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
