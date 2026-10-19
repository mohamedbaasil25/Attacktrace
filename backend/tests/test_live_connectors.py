"""Phase 13 Part B: live connectors. Loopback only; no hardware, no outside network."""

import ast
import asyncio
import random
import socket
import time
from pathlib import Path

import pytest

from app.config import Settings
from app.live.align import Aligner
from app.live.config import LiveConfig, LiveConfigError, load_live
from app.live.modbus import ModbusPoller, ReadError, ReadOnlyModbus
from app.live.quality import ADVISORY, EXCLUDED, QualityTracker, TagSpec, excluded_from_ranking
from app.live.source import LiveSource
from app.live.tagmap import TagMap, encode, load_tagmap

REPO = Path(__file__).resolve().parents[2]
TAGMAP = REPO / "config" / "tagmap.yaml"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def settings(**kw: object) -> Settings:
    base: dict[str, object] = {"live_tagmap": TAGMAP, "live_poll_s": 0.05, "live_timeout_s": 0.5}
    return Settings(**(base | kw))  # type: ignore[arg-type]


# ------------------------------------------------------------------------------- config
def test_default_config_is_valid() -> None:
    cfg, tm = load_live(Settings(live_tagmap=TAGMAP))
    assert cfg.poll_s == 0.25 and cfg.port == 5020 and len(tm.by_role("value")) == 9


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        ("live_port", 0, "AT_LIVE_PORT"),
        ("live_host", " ", "AT_LIVE_HOST"),
        ("live_poll_s", 0.001, "AT_LIVE_POLL_S"),
        ("live_timeout_s", 0.0, "AT_LIVE_TIMEOUT_S"),
        ("live_stale_after_s", 0.1, "AT_LIVE_STALE_AFTER_S"),
        ("live_max_age_s", 0.5, "AT_LIVE_MAX_AGE_S"),
        ("live_max_in_flight", 0, "AT_LIVE_MAX_IN_FLIGHT"),
        ("live_backoff_base_s", 9.0, "AT_LIVE_BACKOFF_BASE_S"),
    ],
)
def test_bad_config_fails_fast_with_a_clear_message(field: str, value: object, needle: str) -> None:
    with pytest.raises(LiveConfigError, match=needle):
        LiveConfig.from_settings(Settings(live_tagmap=TAGMAP, **{field: value}))  # type: ignore[arg-type]


def test_missing_or_broken_tagmap_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(LiveConfigError, match="cannot read"):
        load_live(Settings(live_tagmap=tmp_path / "nope.yaml"))
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\ntags: []\n", encoding="utf-8")
    with pytest.raises(LiveConfigError, match="no value tag"):
        load_live(Settings(live_tagmap=bad))


# ------------------------------------------------------------------------------- alignment
def test_aligner_holds_the_last_value_until_max_age() -> None:
    a = Aligner(["x"], max_age_s=2.0)
    assert a.at("x", 10.0) is None
    assert a.add("x", 1.0, 10.0) and a.add("x", 2.0, 10.5)
    s = a.at("x", 10.7)
    assert s is not None and s.value == 2.0  # newest sample not after t
    s = a.at("x", 10.2)
    assert s is not None and s.value == 1.0  # not the sample from the future
    assert a.at("x", 12.4) is not None  # 1.9 s old
    assert a.at("x", 12.6) is None  # held too long


def test_out_of_order_samples_are_dropped_and_counted() -> None:
    a = Aligner(["x"], max_age_s=5.0)
    assert a.add("x", 1.0, 5.0)
    assert not a.add("x", 9.0, 4.0)  # older than the newest
    assert not a.add("x", 9.0, 5.0)  # same timestamp: ignored, not an error
    assert (a.dropped_out_of_order, a.duplicates, a.accepted) == (1, 1, 1)
    last = a.last("x")
    assert last is not None and last.value == 1.0


# ------------------------------------------------------------------------------- quality
def tracker() -> QualityTracker:
    specs = {
        "S1": TagSpec(0, 100, sensor=True),
        "S2": TagSpec(0, 10, sensor=True),
        "A1": TagSpec(0, 1, sensor=False),
    }
    return QualityTracker(specs, stale_after_s=1.0, max_age_s=5.0, frozen_after_s=30.0)


def test_quality_labels() -> None:
    q = tracker()
    assert q.classify("S1", 0.0) == "missing"  # never read
    q.observe("S1", 50.0, 0.0)
    assert q.classify("S1", 0.5) == "good"
    assert q.classify("S1", 1.5) == "stale"
    assert q.classify("S1", 5.5) == "missing"
    q.observe("S1", 250.0, 10.0)
    assert q.classify("S1", 10.1) == "out_of_range"  # a corrupted value, not an attack
    q.observe("S1", float("nan"), 11.0)
    assert q.classify("S1", 11.1) == "out_of_range"
    q.observe("S1", 103.0, 12.0)
    assert q.classify("S1", 12.1) == "good"  # inside the 5% margin


def test_frozen_needs_neighbours_that_move_and_only_sensors() -> None:
    q = tracker()
    for i in range(80):  # 40 s at 2 Hz
        t = i * 0.5
        q.observe("S1", 50.0, t)  # never changes
        q.observe("S2", 5.0 + (i % 3) * 0.1, t)  # keeps moving
        q.observe("A1", 0.0, t)  # actuator at rest is normal
    now = 39.6
    assert q.classify("S1", now) == "frozen"
    assert q.classify("S2", now) == "good"
    assert q.classify("A1", now) == "good"
    q2 = tracker()  # everything quiet: nothing is "frozen" relative to its neighbours
    for i in range(80):
        for tag, v in (("S1", 50.0), ("S2", 5.0), ("A1", 0.0)):
            q2.observe(tag, v, i * 0.5)
    assert q2.classify("S1", 39.6) == "good"


def test_frozen_is_advisory_and_the_rest_are_excluded() -> None:
    assert "frozen" in ADVISORY and "frozen" not in EXCLUDED
    assert excluded_from_ranking("stale") and excluded_from_ranking("missing")
    assert excluded_from_ranking("out_of_range")
    assert not excluded_from_ranking("frozen") and not excluded_from_ranking("good")


# ------------------------------------------------------------------------------- poller
class FakeClient:
    """A Modbus 'server' in memory: serves registers built from a tag map, with fault hooks."""

    def __init__(self, tm: TagMap, values: dict[str, float] | None = None) -> None:
        self.tm, self.is_up, self.connect_ok = tm, False, True
        self.values = values or {t.tag: 10.0 + i for i, t in enumerate(tm.by_role("value"))}
        self.requests: list[tuple[int, int]] = []
        self.fail: set[int] = set()  # block start addresses that raise
        self.fail_all = False
        self.delay = 0.0
        self.live = 0
        self.peak = 0
        self.closed = 0

    @property
    def connected(self) -> bool:
        return self.is_up

    async def connect(self) -> bool:
        self.is_up = self.connect_ok
        return self.connect_ok

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        self.requests.append((address, count))
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail_all or address in self.fail:
                raise ReadError("injected")
            regs = [0] * (address + count)
            for t in self.tm.by_role("value"):
                regs[t.address : t.address + t.width] = encode(t, self.values[t.tag])
            return regs[address : address + count]
        finally:
            self.live -= 1

    async def close(self) -> None:
        self.is_up = False
        self.closed += 1


def poller(
    client: FakeClient, **kw: object
) -> tuple[ModbusPoller, dict[str, list[float]], list[float]]:
    cfg, tm = load_live(settings(live_block_gap=1, **kw))
    got: dict[str, list[float]] = {}
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)
        await asyncio.sleep(0)

    p = ModbusPoller(
        cfg,
        tm,
        lambda tag, v, ts: got.setdefault(tag, []).append(v),
        client_factory=lambda: client,
        sleep=fake_sleep,
        rng=random.Random(1),
    )
    return p, got, slept


async def test_reads_are_batched_by_contiguous_block() -> None:
    tm = load_tagmap(TAGMAP)
    c = FakeClient(tm)
    p, got, _ = poller(c)
    await c.connect()
    assert await p.poll_once(c) == 3
    assert sorted(c.requests) == [(0, 8), (10, 6), (20, 4)]  # 3 requests for 9 tags, not 9
    assert set(got) == {t.tag for t in tm.by_role("value")}
    assert got["LIT101"] == [pytest.approx(c.values["LIT101"])]
    assert got["PLC2"] == [pytest.approx(c.values["PLC2"])]


async def test_a_partial_read_failure_keeps_the_other_tags() -> None:
    c = FakeClient(load_tagmap(TAGMAP))
    c.fail = {10}  # actuator block
    p, got, _ = poller(c)
    await c.connect()
    assert await p.poll_once(c) == 2
    assert "LIT101" in got and "PLC1" in got
    assert not {"MV101", "P101", "P301"} & set(got)
    assert p.reads_failed == 1 and p.reads_ok == 2 and p.last_error == "injected"


async def test_backoff_grows_is_capped_and_resets() -> None:
    c = FakeClient(load_tagmap(TAGMAP))
    c.connect_ok = False
    p, _, slept = poller(c, live_backoff_base_s=0.2, live_backoff_max_s=1.0)
    task = asyncio.create_task(p.run())
    for _ in range(40):
        await asyncio.sleep(0)
    task.cancel()
    delays = p.backoffs
    assert len(delays) >= 6 and p.state == "down"
    for attempt, d in enumerate(delays[:6]):
        base = min(1.0, 0.2 * 2**attempt)
        assert 0.8 * base - 1e-9 <= d <= 1.2 * base + 1e-9  # exponential, +-20% jitter, capped
    assert max(delays) <= 1.2 + 1e-9
    assert len({round(d, 6) for d in delays[-3:]}) > 1  # jitter: not all identical
    assert p.backoff(0) < 0.3 and p.backoff(30) <= 1.2  # attempt counter restarts from 0 on success
    assert slept[: len(delays)] == delays


async def test_the_connection_is_dropped_and_retried_after_total_failure() -> None:
    c = FakeClient(load_tagmap(TAGMAP))
    p, got, _ = poller(c)
    task = asyncio.create_task(p.run())
    for _ in range(30):
        await asyncio.sleep(0)
    assert p.state == "connected" and got
    first = len(got["LIT101"])
    c.fail_all = True
    for _ in range(60):
        await asyncio.sleep(0)
    assert c.closed >= 1 and p.backoffs  # gave up on this connection and backed off
    c.fail_all = False
    for _ in range(80):
        await asyncio.sleep(0)
    task.cancel()
    assert p.state == "connected" and p.reconnects >= 2 and len(got["LIT101"]) > first


async def test_requests_in_flight_are_bounded() -> None:
    for limit in (1, 2):
        c = FakeClient(load_tagmap(TAGMAP))
        c.delay = 0.01
        p, _, _ = poller(c, live_max_in_flight=limit)
        await c.connect()
        await p.poll_once(c)
        assert c.peak == limit


async def test_a_silent_server_times_out_instead_of_hanging() -> None:
    async def silent(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        await asyncio.sleep(30)

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = ReadOnlyModbus("127.0.0.1", port, timeout_s=0.3, device_id=1)
    assert await client.connect()
    t0 = time.perf_counter()
    with pytest.raises(ReadError):
        await client.read_input_registers(0, 2)
    assert time.perf_counter() - t0 < 2.0
    await client.close()
    server.close()


async def test_connection_refused_is_down_not_a_crash() -> None:
    cfg, tm = load_live(settings(live_port=free_port(), live_backoff_base_s=0.05))
    src = LiveSource(cfg, tm)
    await src.start()
    await asyncio.sleep(1.5)
    st = src.status()
    assert st.state == "down" and not st.connected and st.reason
    assert not src.ready
    await src.stop()


# ------------------------------------------------------------------------------- source
def source_with_samples(now: float) -> LiveSource:
    cfg, tm = load_live(settings())
    src = LiveSource(cfg, tm, clock=lambda: now)
    for t in tm.by_role("value"):
        src._on_sample(t.tag, (t.min + t.max) / 2.0, now)
    return src


def test_snapshot_status_and_health_label_stale_and_missing_data() -> None:
    src = source_with_samples(100.0)
    snap = src.snapshot(100.2)
    assert snap.ready and set(snap.quality.values()) == {"good"}
    assert snap.values["LIT101"] == 50.0 and snap.source_latency_ms == pytest.approx(200.0)
    snap = src.snapshot(101.6)  # 1.6 s without an update
    assert set(snap.quality.values()) == {"stale"} and snap.values["LIT101"] == 50.0  # held
    snap = src.snapshot(110.0)
    assert set(snap.quality.values()) == {"missing"}
    health = {h.tag: h for h in src.health(101.6)}
    assert health["LIT101"].quality == "stale" and health["LIT101"].age_ms == pytest.approx(1600.0)
    assert health["LIT101"].last_value == 50.0 and health["LIT101"].node_id == "LIT101"


def test_a_corrupt_value_is_out_of_range_not_a_false_origin_input() -> None:
    src = source_with_samples(50.0)
    src._on_sample("LIT101", 4000.0, 50.5)
    snap = src.snapshot(50.6)
    assert snap.quality["LIT101"] == "out_of_range"
    assert snap.quality["LIT301"] == "good"
    assert excluded_from_ranking(snap.quality["LIT101"])


def test_source_not_ready_until_every_node_was_read() -> None:
    cfg, tm = load_live(settings())
    src = LiveSource(cfg, tm, clock=lambda: 1.0)
    src._on_sample("LIT101", 50.0, 1.0)
    assert not src.snapshot().ready and not src.ready


def test_out_of_order_samples_reach_the_dropped_counter() -> None:
    src = source_with_samples(10.0)
    src._on_sample("LIT101", 1.0, 9.0)
    src._on_sample("LIT101", 1.0, 8.0)
    assert src.status(10.1).dropped == 2


# ---------------------------------------------------------------- reconnect (real server)
async def test_the_source_reconnects_after_the_server_restarts() -> None:
    from plant_emulator.server import PlantEmulator

    port = free_port()
    cfg, tm = load_live(
        settings(
            live_port=port, live_backoff_base_s=0.05, live_backoff_max_s=0.2, live_timeout_s=0.3
        )
    )
    emu = PlantEmulator(tm, port=port, health_port=None)
    await emu.start()
    src = LiveSource(cfg, tm)
    await src.start()
    try:
        for _ in range(60):
            if src.ready and src.status().state == "connected":
                break
            await asyncio.sleep(0.05)
        assert src.ready and src.status().connected
        n_before = src.aligner.accepted

        await emu.stop()  # the server goes away
        for _ in range(100):
            if not src.status().connected:
                break
            await asyncio.sleep(0.05)
        assert not src.status().connected and src.status().reason

        emu2 = PlantEmulator(tm, port=port, health_port=None)
        await emu2.start()  # ...and comes back on the same port
        try:
            for _ in range(200):
                if src.status().state == "connected" and src.aligner.accepted > n_before + 20:
                    break
                await asyncio.sleep(0.05)
            assert src.status().state == "connected"
            assert src.aligner.accepted > n_before + 20  # data flows again
            assert src.poller.reconnects >= 2
        finally:
            await emu2.stop()
    finally:
        await src.stop()


# ---------------------------------------------------------------- read-only guarantee
async def test_the_live_package_has_no_write_path() -> None:
    """AttackTrace's ingestion may read the plant; this fails if app/live can write to it.

    Writing local files (models, SQLite) is fine; Modbus writes and importing the attacker or the
    emulator are not."""
    import re

    forbidden = re.compile(r"^(mask_write_register|readwrite_registers|write_(registers?|coils?))$")
    bad: list[str] = []
    for path in sorted((Path(__file__).resolve().parents[1] / "app" / "live").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                name = node.name
            if name and forbidden.match(name):
                bad.append(f"{path.name}:{node.lineno}:{name}")
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            bad += [
                f"{path.name}:{node.lineno}:imports {m}"
                for m in mods
                if m.split(".")[0] in {"attacker", "plant_emulator"}
            ]
    assert bad == []
    c = ReadOnlyModbus("127.0.0.1", 1, 0.1, 1)
    assert not [a for a in dir(c) if "write" in a.lower()]
    with pytest.raises(AttributeError):
        c.write_registers  # type: ignore[attr-defined]  # noqa: B018
    assert not hasattr(c, "__dict__")  # __slots__: no way to attach or reach a writer
