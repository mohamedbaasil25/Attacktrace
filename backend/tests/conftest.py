from pathlib import Path

import numpy as np
import pytest
import torch

from app.config import Settings
from app.data.simdata import simulate
from app.detect.baseline import BaselineDetector
from app.detect.detector import ForecastDetector, aggregate, fit_err_sd
from app.detect.forecaster import WINDOW, Norm, build_model, make_windows, train
from app.detect.pipeline import Loaded
from app.engine import Engine
from app.graph import adjacency, static_graph
from app.sim import NODE_IDS


@pytest.fixture(scope="session")
def tiny() -> tuple[Loaded, BaselineDetector]:
    """Small, quickly trained detector: enough to flag large attacks, not tuned for accuracy."""
    train_runs = [simulate(s, 300.0).x for s in (11, 12, 13)]
    val_runs = [simulate(s, 300.0).x for s in (14, 15)]
    norm = Norm.fit(np.vstack(train_runs))
    tx = [make_windows(norm.apply(x)) for x in train_runs]
    xy = (np.concatenate([a for a, _ in tx]), np.concatenate([b for _, b in tx]))
    vx = [make_windows(norm.apply(x)) for x in val_runs]
    vxy = (np.concatenate([a for a, _ in vx]), np.concatenate([b for _, b in vx]))
    torch.manual_seed(0)  # the test detector must not depend on what ran before it
    model = build_model("gdn", len(NODE_IDS), WINDOW, adjacency(static_graph()))
    train(model, xy, vxy, epochs=15)
    det = ForecastDetector(model, norm, fit_err_sd(model, norm, val_runs))
    clean = [det.score_run(x)[WINDOW:] for x in val_runs]
    node_thr = np.quantile(np.vstack(clean), 0.999, axis=0)
    threshold = 1.2 * max(float(aggregate(c).max()) for c in clean)
    base = BaselineDetector().fit(np.vstack(train_runs))
    return Loaded(det, threshold, node_thr), base


@pytest.fixture
def engine(tiny: tuple[Loaded, BaselineDetector]) -> Engine:
    loaded, base = tiny
    return Engine(loaded, base, static_graph(), Settings(), detector_kind="gdn")


@pytest.fixture(scope="session")
def hai_dir(tmp_path_factory: pytest.TempPathFactory) -> "Path":
    from tests.hai_fixture import make_dataset

    return make_dataset(tmp_path_factory.mktemp("hai"))


@pytest.fixture(scope="session")
def hai_models(hai_dir: "Path", tmp_path_factory: pytest.TempPathFactory) -> "Path":
    """Detectors trained on the synthetic dataset (2 epochs: enough to see a +3 offset)."""
    from app.detect.hai_pipeline import train_hai

    models = tmp_path_factory.mktemp("hai_models")
    train_hai(models, hai_dir, epochs=2, log=False)
    return models
