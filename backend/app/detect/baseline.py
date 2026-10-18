"""Baseline detector for the comparison panel: Isolation Forest + per-node 3-sigma thresholds."""

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import IsolationForest

from app.detect.forecaster import Norm
from app.sim import NODE_IDS

F64 = NDArray[np.float64]

SIGMA = 3.0


class BaselineDetector:
    # Class-level default: baselines pickled before `names` existed (SIM models on disk) load
    # without the instance attribute and must keep working.
    names: tuple[str, ...] = NODE_IDS

    def __init__(
        self, contamination: float = 0.001, seed: int = 0, names: tuple[str, ...] = NODE_IDS
    ) -> None:
        self.names = names
        self._forest = IsolationForest(contamination=contamination, random_state=seed)
        self.norm: Norm | None = None

    def fit(self, x: F64) -> "BaselineDetector":
        self.norm = Norm.fit(x)
        self._forest.fit(self.norm.apply(x))
        return self

    def _z(self, x: F64) -> F64:
        assert self.norm is not None, "fit() first"
        return self.norm.apply(x)

    def zscores(self, x: F64) -> F64:
        """(T, N) absolute distance from the clean mean in clean standard deviations."""
        return np.asarray(np.abs(self._z(x)), dtype=np.float64)

    def breaches(self, x: F64) -> NDArray[np.bool_]:
        """(T, N): node outside its clean ±3-sigma band, the per-node alarms a SOC would see."""
        return np.abs(self._z(x)) > SIGMA

    def alarms(self, x_t: F64) -> list[str]:
        row = self.breaches(x_t[None, :])[0]
        return [n for n, hit in zip(self.names, row, strict=True) if hit]

    def alert(self, x: F64) -> NDArray[np.bool_]:
        """(T,): any 3-sigma breach or an Isolation Forest outlier."""
        outlier = self._forest.predict(self._z(x)) == -1
        return np.asarray(self.breaches(x).any(axis=1) | outlier)
