from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.data.hai import HaiData, hai_paths, load_hai, node_kind, process_of
from app.detect.hai_pipeline import (
    hai_models_ready,
    load_hai_baseline,
    load_hai_detector,
    split_tests,
)
from app.engine import Engine
from app.engine_hai import HaiEngine
from app.main import create_app
from app.schemas import LiveMessage
from eval.hai import (
    evaluate_detector,
    process_scores,
    truth_processes,
)
from tests.hai_fixture import CONSTANT, FEATURES, TEST1_ATTACK, TEST2_ATTACK


@pytest.fixture(scope="module")
def data(hai_dir: Path) -> HaiData:
    return load_hai(hai_dir)


# ------------------------------------------------------------------------------- loader
def test_paths_ignore_missing_folder_and_other_files(tmp_path: Path, hai_dir: Path) -> None:
    assert hai_paths(tmp_path / "nope") == []
    (tmp_path / "notes.txt").write_text("x")
    assert hai_paths(tmp_path) == []
    assert [p.name for p in hai_paths(hai_dir)] == ["test1.csv.gz", "test2.csv.gz", "train1.csv.gz"]


def test_load_drops_constant_columns_and_keeps_labels(data: HaiData) -> None:
    assert data.features == FEATURES and CONSTANT not in data.features
    assert [f.name for f in data.tests] == ["test1", "test2"]
    t1 = data.tests[0]
    assert t1.x.shape[1] == len(FEATURES)
    assert t1.windows() == [TEST1_ATTACK]
    assert t1.by_process[TEST1_ATTACK[0]].tolist() == [1, 0, 0]
    assert data.tests[1].windows() == [TEST2_ATTACK]
    assert data.train[0].attack.sum() == 0


def test_labels_mark_recovery_as_ignored(data: HaiData) -> None:
    f = data.tests[0]
    y = f.labels()
    s, e = TEST1_ATTACK
    assert (y[s:e] == 1).all() and y[s - 1] == 0
    assert (y[e : e + 60] == -1).all() and y[e + 60] == 0


def test_train_files_are_required(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_hai(tmp_path)


def test_tag_naming_heuristics() -> None:
    assert process_of("P3_LCV01D") == "P3" and process_of("weird") == "P1"
    assert node_kind("P1_B2004") == "controller"
    assert node_kind("P1_FCV01D") == "actuator"
    assert node_kind("P1_LIT01") == "sensor"


def test_one_test_file_is_not_enough(data: HaiData) -> None:
    tune, held = split_tests(data)
    assert tune.name == "test2" and [f.name for f in held] == ["test1"]
    with pytest.raises(ValueError):
        split_tests(HaiData(data.features, data.train, data.tests[:1]))


# ---------------------------------------------------------------------------- training
def test_trained_models_round_trip(hai_models: Path) -> None:
    assert hai_models_ready(hai_models)
    loaded = load_hai_detector(hai_models)
    assert list(loaded.features) == FEATURES and len(loaded.types) == len(FEATURES)
    assert loaded.graph.number_of_nodes() == len(FEATURES)
    assert all(d["kind"] == "learned" for *_, d in loaded.graph.edges(data=True))
    assert loaded.threshold > 0 and (loaded.node_thr > 0).all()
    assert load_hai_baseline(hai_models).names == tuple(FEATURES)


# ------------------------------------------------------------------------------ engine
@pytest.fixture
def hai_engine(hai_models: Path, data: HaiData) -> HaiEngine:
    return HaiEngine(
        load_hai_detector(hai_models), load_hai_baseline(hai_models), data.tests[0], Settings()
    )


def test_replay_starts_before_the_first_attack_and_follows_the_speed(hai_engine: HaiEngine) -> None:
    assert hai_engine._pos == TEST1_ATTACK[0] - 300  # 5 minutes of lead-in
    msg = hai_engine.step_sample()
    assert msg.mode == "hai" and msg.impact is None
    assert [n.id for n in msg.nodes] == FEATURES
    assert all(n.truth is None for n in msg.nodes)
    assert hai_engine._pos == TEST1_ATTACK[0] - 300 + 5  # x10 speed, 0.5 s tick -> 5 rows


def test_speed_is_clamped_to_the_supported_range(hai_models: Path, data: HaiData) -> None:
    def speed(v: float) -> float:
        e = HaiEngine(
            load_hai_detector(hai_models),
            load_hai_baseline(hai_models),
            data.tests[0],
            Settings(hai_speed=v),
        )
        return e.speed

    assert speed(0.1) == 1.0 and speed(99) == 20.0 and speed(7) == 7.0


def test_slow_speed_carries_fractions(hai_models: Path, data: HaiData) -> None:
    e = HaiEngine(
        load_hai_detector(hai_models),
        load_hai_baseline(hai_models),
        data.tests[0],
        Settings(hai_speed=1.0),
    )
    start = e._pos
    for _ in range(4):
        e.step_sample()
    assert e._pos == start + 2  # x1 = one row per second = every other 0.5 s tick


def test_dataset_attack_becomes_an_incident_without_invented_labels(hai_engine: HaiEngine) -> None:
    msgs: list[LiveMessage] = []
    for _ in range(120):
        msgs.append(hai_engine.step_sample())
    inc = next((m.incident for m in reversed(msgs) if m.incident), None)
    assert inc is not None, "the +3 offset on P1_A must raise an incident"
    assert inc.origin[0].id in {"P1_A", "P1_B"}  # the attacked tag or its direct follower
    assert inc.mitre == "" and inc.mitre_name == "" and inc.ground_truth is None
    assert inc.explanation.startswith("Origin ") and inc.action.startswith("Inspect P1")
    assert hai_engine.incidents and hai_engine.incidents[-1].status == "closed"  # attack is over
    live = [m for m in msgs if m.incident and m.incident.status != "closed"]
    assert live, "the incident was visible while the attack ran"
    flagged = {n.id for m in live for n in m.nodes if n.status == "origin"}
    assert inc.origin[0].id in flagged  # the origin node was marked on the live stream


def test_reset_restarts_the_replay_and_the_replay_loops(hai_engine: HaiEngine) -> None:
    for _ in range(30):
        hai_engine.step_sample()
    hai_engine.reset()
    assert hai_engine._pos == TEST1_ATTACK[0] - 300
    assert hai_engine.incidents == [] and hai_engine.latest is None
    hai_engine._pos = len(hai_engine.replay.x) - 2
    hai_engine.step_sample()
    assert hai_engine._pos < len(hai_engine.replay.x) // 2  # wrapped to the start


def test_topology_lists_dataset_tags(hai_engine: HaiEngine) -> None:
    topo = hai_engine.topology()
    assert [n.id for n in topo.nodes] == FEATURES
    assert topo.edges and all(e.kind == "learned" for e in topo.edges)
    assert all(n.lo <= n.hi for n in topo.nodes)


# ------------------------------------------------------------------------- evaluation
def test_truth_process_and_scoring(data: HaiData) -> None:
    f = data.tests[0]
    assert truth_processes(f, *TEST1_ATTACK) == {"P1"}
    assert truth_processes(f, 0, 10) == set()
    assert process_scores(["P1_A", "P2_D", "P3_E"], {"P1"}) == (True, True)
    assert process_scores(["P2_D", "P1_A", "P3_E"], {"P1"}) == (False, True)
    assert process_scores(["P2_D", "P3_E", "P4_F"], {"P1"}) == (False, False)


def test_detector_metrics_on_a_known_alert_pattern(data: HaiData) -> None:
    f = data.tests[0]
    alert = np.zeros(len(f.x), dtype=bool)
    s, e = TEST1_ATTACK
    alert[s + 50 : e] = True  # detected 50 s late, no false alarms
    m = evaluate_detector("x", f, alert)
    assert m["precision"] == 1.0 and m["windows_detected"] == 1.0 and m["n_windows"] == 1
    assert m["mean_detection_delay_s"] == 50.0 and m["false_alarm_per_hour"] == 0.0
    assert m["recall"] == pytest.approx(150 / 200)
    assert m["f1_point_adjusted"] == 1.0  # one alert inside the attack credits all of it
    noisy = alert.copy()
    noisy[100:110] = True
    assert evaluate_detector("x", f, noisy)["false_alarm_per_hour"] > 0


# -------------------------------------------------------------------------------- API
@pytest.fixture
def client(
    engine: Engine, hai_engine: HaiEngine, hai_dir: Path, tmp_path: Path
) -> Iterator[TestClient]:
    app = create_app(engine, run_loop=False, hai_engine=hai_engine)
    app.state.reports_dir, app.state.hai_dir = tmp_path, hai_dir
    with TestClient(app) as c:
        yield c


def test_mode_switch_streams_hai_and_back(client: TestClient) -> None:
    assert client.get("/api/status").json()["hai_available"] is True
    res = client.post("/api/mode", json={"mode": "hai"})
    assert res.status_code == 200 and res.json()["mode"] == "hai"
    assert res.json()["detector_active"] in {"gdn", "mlp"}
    assert [n["id"] for n in client.get("/api/topology").json()["nodes"]] == FEATURES
    assert (
        client.post("/api/attack", json={"scenario": "sensor_offset", "target": "P1_A"}).status_code
        == 409
    )
    assert client.post("/api/reset").json()["mode"] == "hai"
    hai = client.app.state.hai  # type: ignore[attr-defined]
    hai.step_sample()
    with client.websocket_connect("/ws/live") as ws:
        assert LiveMessage.model_validate_json(ws.receive_text()).mode == "hai"
    assert client.post("/api/mode", json={"mode": "sim"}).json()["mode"] == "sim"
    assert len(client.get("/api/topology").json()["nodes"]) == 9


def test_hai_mode_is_refused_without_data_or_models(
    engine: Engine, hai_dir: Path, tmp_path: Path
) -> None:
    app = create_app(engine, run_loop=False)  # files present, no replay engine built
    app.state.reports_dir, app.state.hai_dir = tmp_path, hai_dir
    with TestClient(app) as c:
        assert c.post("/api/mode", json={"mode": "hai"}).status_code == 503
        app.state.hai_dir = tmp_path / "missing"
        assert c.get("/api/status").json()["hai_available"] is False
        assert c.post("/api/mode", json={"mode": "hai"}).status_code == 409
        assert c.post("/api/mode", json={"mode": "sim"}).status_code == 200


def test_suspect_needs_both_a_high_score_and_a_departure_from_the_nodes_own_normal(
    hai_engine: HaiEngine,
) -> None:
    e = hai_engine
    for _ in range(30):  # let the adaptive baseline warm up on the quiet lead-in
        e.step_sample()
    thr = float(e.loaded.node_thr[0])
    e._scores[0] = 1.5 * thr  # above its clean threshold...
    e._slow[0] = 1.5 * thr  # ...but that is simply how this node runs today
    assert not e._unusual(0, thr)
    e._slow[0] = 0.2 * thr  # now it is far above its own recent behaviour
    assert e._unusual(0, thr)
    e._scores[0] = 0.5 * thr  # and a low score is never suspect
    assert not e._unusual(0, thr)
    e._k = 5  # before the baseline warms up nothing is suspect
    e._scores[0] = 3 * thr
    assert not e._unusual(0, thr)


def test_transient_read_errors_are_retried(monkeypatch: pytest.MonkeyPatch, hai_dir: Path) -> None:
    import pandas as pd

    from app.data import hai as hai_mod

    real, calls = pd.read_csv, {"n": 0}

    def flaky(path: Path, **kw: object) -> pd.DataFrame:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError(14, "Bad address")
        return real(path, **kw)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(hai_mod.pd, "read_csv", flaky)
    monkeypatch.setattr(hai_mod.time, "sleep", lambda s: None)
    df = hai_mod._read_csv(hai_dir / "train1.csv.gz")
    assert calls["n"] == 3 and len(df) > 0

    calls["n"] = -100  # never succeeds: the error must surface after the last attempt
    with pytest.raises(OSError):
        hai_mod._read_csv(hai_dir / "train1.csv.gz")
