"""Phase 2/3 audit: regression tests for the detection pipeline's evidence integrity and
persistence.

Covers the `_truth_for` staleness fix (ground truth must come from an attack genuinely live at
the moment an incident is created, not merely the most recently launched one), duplicate/repeated
attack handling, SIM incident restart-survival (Phase 3), and the tag historian's own persistence.
See `tests/test_ledger.py` for the hash-chain and verification-API coverage.
"""

from pathlib import Path

from app.attacks import Scenario
from app.config import Settings
from app.detect.baseline import BaselineDetector
from app.detect.pipeline import Loaded
from app.engine import Engine
from app.evidence import IncidentStore
from app.graph import static_graph
from app.history import HistoryStore
from app.schemas import AttackRequest, Incident, LiveMessage, NodeState


def run(engine: Engine, seconds: float) -> list[LiveMessage]:
    return [engine.step_sample() for _ in range(round(seconds / 0.5))]


def run_until_closed(engine: Engine, max_seconds: float = 150) -> None:
    for _ in range(round(max_seconds / 0.5)):
        engine.step_sample()
        if engine.incidents and engine.incidents[-1].status == "closed":
            return
    raise AssertionError("incident never closed")


# --------------------------------------------------------------------- ground-truth attribution
def test_ground_truth_ignores_an_attack_that_already_ended(engine: Engine) -> None:
    """A short attack that finished minutes ago must never be reported as the cause of a later,
    unrelated incident just because it happens to be the most recently *launched* one -- that is
    fabricated forensic evidence, not a real finding. Regression for `Engine._truth_for`."""
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=10))
    run_until_closed(engine)  # the attack ends, and its incident runs its course to "closed"

    second = engine.launch(
        AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P301", duration_s=300)
    )
    opened = None
    for m in run(engine, 30):
        if m.incident is not None:
            opened = m.incident
    assert opened is not None
    assert opened.ground_truth is not None
    assert opened.ground_truth.attack_id == second  # not `first`, even though it launched earlier
    assert opened.ground_truth.target == "P301"


# ----------------------------------------------------------------------------- duplicate events
def test_overlapping_duplicate_attacks_on_the_same_node_fold_into_one_incident(
    engine: Engine,
) -> None:
    """Launching the same scenario on the same node twice while it is already under attack (a
    double-click, a retried request) must not spawn a second, duplicate incident -- the node's
    own persistence counter only crosses once per sustained excursion."""
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=300))
    run(engine, 15)
    assert len(engine.incidents) == 1
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=300))
    run(engine, 15)
    assert len(engine.incidents) == 1  # still one incident, not two


def test_repeated_attacks_each_get_their_own_correct_incident(engine: Engine) -> None:
    """The same scenario fired twice on the same node, with the first incident fully closed in
    between, must produce two separate incidents, each attributed to its own attack."""
    first = engine.launch(
        AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=10)
    )
    run_until_closed(engine)
    assert engine.incidents[-1].status == "closed"
    assert engine.incidents[-1].ground_truth is not None
    assert engine.incidents[-1].ground_truth.attack_id == first

    second = engine.launch(
        AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=300)
    )
    opened = None
    for m in run(engine, 30):
        if m.incident is not None:
            opened = m.incident
    assert opened is not None and opened.id != engine.incidents[0].id
    assert opened.ground_truth is not None and opened.ground_truth.attack_id == second


# ------------------------------------------------------------------------------ UI/API honesty
def test_isolate_is_refused_against_a_nonexistent_incident(engine: Engine) -> None:
    """The engine never reports an action as applied when there was nothing to apply it to --
    the API/UI layers trust this return value as the sole source of truth for "did it work"."""
    accepted, reason = engine.isolate("inc_does_not_exist", "P101")
    assert accepted is False and reason == "Incident is not active"


# -------------------------------------------------------------------------- historian persistence
def test_history_store_survives_being_reopened(tmp_path: Path) -> None:
    """Simulates a backend restart: a second `HistoryStore` pointed at the same file must see
    everything the first one wrote."""
    path = tmp_path / "history.sqlite"
    store = HistoryStore(path)
    store.record(
        LiveMessage(
            t=1.0,
            mode="sim",
            nodes=[NodeState(id="LIT101", value=50.0, truth=None, score=0.1, status="normal")],
            alert=None,
            incident=None,
            incidents=[],
            impact=None,
        )
    )
    store.close()

    reopened = HistoryStore(path)
    rows = reopened.query("LIT101")
    reopened.close()
    assert [r.value for r in rows] == [50.0]


def test_sim_incidents_survive_a_restart(
    tiny: tuple[Loaded, BaselineDetector], tmp_path: Path
) -> None:
    """Phase 3 supersedes Phase 2's "SIM incidents do not survive a restart" finding: with a
    shared `IncidentStore`, they now do, the same way LIVE already did
    (`test_live_runtime.py::test_incidents_survive_a_restart_and_ids_continue`)."""
    loaded, base = tiny
    store = IncidentStore(tmp_path / "incidents.sqlite")
    first = Engine(loaded, base, static_graph(), Settings(), detector_kind="gdn", store=store)
    first.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=300))
    run(first, 20)
    assert first.incidents and first.incidents[0].status in ("localizing", "open")
    before = first.incidents[0]
    store.close()

    reopened = IncidentStore(tmp_path / "incidents.sqlite")  # the process restarts
    second = Engine(loaded, base, static_graph(), Settings(), detector_kind="gdn", store=reopened)
    assert [i.id for i in second.incidents] == [before.id]
    assert second.incidents[0].status == "closed"  # nothing was watching it when "the process" died
    assert second._next_incident_id == 2  # a fresh incident will not collide with inc_001
    reopened.close()


# --------------------------------------------------------------------------- evidence integrity
def _sample_incident(id_: str = "inc_001") -> Incident:
    return Incident(
        id=id_,
        status="open",
        detected_at=1.0,
        origin=[],
        path=[],
        path_edges=[],
        explanation="x",
        action="x",
        mitre="T0856",
        mitre_name="Spoof Reporting Message",
        baseline_alarms=[],
        ground_truth=None,
        mode="live",
        ambiguous=False,
    )


def test_incident_store_now_has_a_ledger_table_with_a_hash_chain(tmp_path: Path) -> None:
    """Phase 2 found no hash chain anywhere; Phase 3 adds one, in the same database file as the
    `incidents` table (not a second, competing store -- see `app/evidence.py`'s module
    docstring)."""
    store = IncidentStore(tmp_path / "incidents.sqlite")
    cols = {row[1] for row in store._db.execute("PRAGMA table_info(ledger)").fetchall()}
    store.close()
    assert cols == {
        "seq",
        "event_id",
        "ts",
        "event_type",
        "entity_id",
        "payload",
        "prev_hash",
        "hash",
    }


def test_current_state_updates_no_longer_erase_the_historical_record(tmp_path: Path) -> None:
    """`IncidentStore.save` still does `INSERT OR REPLACE` on the `incidents` table -- that is the
    correct, legitimate behavior for a current-state projection (Phase 3's architecture note).
    What Phase 2 actually found wrong is now fixed: the *ledger* preserves both the original and
    the updated version as separate, hash-linked records, so the fact that the row got updated at
    all is never lost the way it used to be."""
    store = IncidentStore(tmp_path / "incidents.sqlite")
    original = _sample_incident()
    store.save(original, event_type="incident_created")

    updated = original.model_copy(update={"status": "closed"})
    store.save(updated, event_type="status_changed", detail={"from": "open", "to": "closed"})

    (loaded,) = store.load("live")  # the current-state row: still just the latest version
    assert loaded.status == "closed"

    rows = store._db.execute("SELECT event_type, entity_id FROM ledger ORDER BY seq").fetchall()
    store.close()
    assert rows == [
        ("genesis", ""),
        ("incident_created", "inc_001"),
        ("status_changed", "inc_001"),
    ]  # both the creation AND the update survive, in order, unlike the old `incidents`-only table
