"""FastAPI entrypoint: CORS, routers, and the background engine task."""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import rest, ws
from app.api.auth import load_operators
from app.api.live_attack import LiveAttackLauncher
from app.api.security import LoginLockout, RateLimiter
from app.config import Settings, get_settings
from app.data.hai import hai_paths, load_hai
from app.detect.hai_pipeline import (
    hai_models_ready,
    load_hai_baseline,
    load_hai_detector,
    train_hai,
)
from app.detect.pipeline import load_baseline, load_detector, train_all
from app.engine import Engine
from app.engine_hai import HaiEngine
from app.evidence import IncidentStore
from app.graph import load_graph
from app.history import HistoryStore
from app.live.runtime import LiveRuntime, build_live_runtime
from app.siem import SiemNotifier
from app.storage import HistoryStoreLike, IncidentStoreLike

log = logging.getLogger("attacktrace")


def ensure_metrics(settings: Settings) -> bool:
    """Write reports/metrics.json on a fresh start so /metrics works immediately.

    Runs before the server accepts traffic (a minute or so), so it never competes with the live
    loop for CPU. Returns True when it ran."""
    path = settings.reports_dir / "metrics.json"
    stale = (
        path.exists() and hai_paths(settings.hai_dir) and "hai" not in json.loads(path.read_text())
    )
    if path.exists() and not stale:  # also refresh files written before HAI data was added
        return False
    from eval.run import write_metrics  # imported lazily: only needed on a first start

    log.warning("no metrics.json in %s - evaluating once (about a minute)", settings.reports_dir)
    write_metrics(settings)
    return True


def safe_ensure_metrics(settings: Settings) -> bool:
    """`ensure_metrics` that cannot stop the app: metrics are a convenience, and the optional HAI
    part reads a large dataset. A failure is logged and /metrics shows what exists (or 404)."""
    try:
        return ensure_metrics(settings)
    except Exception:
        log.exception("metrics could not be generated; continuing without them")
        return False


def build_hai_engine(
    settings: Settings, store: IncidentStoreLike | None = None
) -> HaiEngine | None:
    """HAI replay engine when HAI files are present. Never raises: a failure just leaves HAI
    mode unavailable (the API answers 503) and SIM running."""
    if not hai_paths(settings.hai_dir):
        return None
    try:
        d = settings.models_dir
        if not hai_models_ready(d):
            log.warning("no HAI models in %s/hai - training (about two minutes)", d)
            train_hai(d, settings.hai_dir, log=False)
        data = load_hai(settings.hai_dir)
        replay = next((f for f in data.tests if f.name == settings.hai_file), data.tests[0])
        return HaiEngine(load_hai_detector(d), load_hai_baseline(d), replay, settings, store=store)
    except Exception:
        log.exception("HAI mode unavailable")
        return None


def build_engine(settings: Settings, store: IncidentStoreLike | None = None) -> Engine:
    """Load trained models (training them first if the models dir is empty)."""
    d = settings.models_dir
    if not (d / "detector.json").exists():
        log.warning("no trained models in %s — training (about a minute)", d)
        train_all(d, log=False)
    safe_ensure_metrics(settings)
    kind = str(json.loads((d / "detector.json").read_text())["active"])
    return Engine(
        load_detector(d, kind),
        load_baseline(d),
        load_graph(d / "graph.json"),
        settings,
        detector_kind=kind,
        store=store,
    )


def create_app(
    engine: Engine | None = None,
    run_loop: bool = True,
    hai_engine: HaiEngine | None = None,
    live_runtime: LiveRuntime | None = None,
    # Protocol-typed (app/storage.py), not the concrete SQLite classes: a test (or, eventually, a
    # Postgres-backed store) only needs to satisfy IncidentStoreLike/HistoryStoreLike, not
    # subclass anything. Production startup below still builds the real `IncidentStore`/
    # `HistoryStore` when neither is injected.
    history: HistoryStoreLike | None = None,
    incidents_store: IncidentStoreLike | None = None,
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.incidents_store = incidents_store
        if incidents_store is None and engine is None:  # production start only: one store for
            # every mode (Phase 3) -- built before any engine so SIM/HAI/LIVE all restore from
            # and persist to the same file, never three competing stores. Never raises: a bad or
            # corrupted database file must not take the whole app down (SIM included) the way it
            # did before this try/except -- same "never blocks SIM/HAI" convention
            # `build_hai_engine` and `build_live_runtime` already follow. Degraded mode: every
            # mode still runs, just without persistence or the audit ledger.
            try:
                app.state.incidents_store = await asyncio.to_thread(IncidentStore, settings.live_db)
            except Exception:
                log.exception(
                    "Incident evidence store unavailable (%s); continuing without persistence "
                    "or the audit ledger",
                    settings.live_db,
                )
                app.state.incidents_store = None
        store = app.state.incidents_store
        app.state.engine = engine or await asyncio.to_thread(build_engine, settings, store)
        app.state.hai = hai_engine
        if hai_engine is None and engine is None:  # production start: look for HAI data too
            app.state.hai = await asyncio.to_thread(build_hai_engine, settings, store)
        if live_runtime is not None:
            app.state.live = live_runtime
        elif engine is None:  # production start: LIVE is optional and never blocks SIM or HAI
            app.state.live, app.state.live_reason = build_live_runtime(settings, store)
        if app.state.live is not None:
            app.state.live_attacker = LiveAttackLauncher(settings.attacker_allowlist)
            await app.state.live.source.start()
        if history is not None:
            app.state.history = history
        elif engine is None:  # production start only: same convention as LIVE above
            # Phase 5.1: never raises, same "a bad database must not take the whole app down"
            # fix already applied to the incidents store (Phase 3.1) -- found missing here only
            # by actually running `docker compose up` against the Phase 5.1 non-root user change,
            # where an unwritable /data/history.sqlite crashed the entire backend instead of just
            # disabling the tag historian.
            try:
                app.state.history = HistoryStore(settings.history_db)
            except Exception:
                log.exception(
                    "Tag historian unavailable (%s); continuing without it", settings.history_db
                )
                app.state.history = None
        task = (
            asyncio.create_task(ws.run_loop(app.state, app.state.hub, settings.ws_period_s))
            if run_loop
            else None
        )
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if app.state.live is not None:
            await app.state.live.stop()
        if app.state.live_attacker is not None:
            await app.state.live_attacker.close()
        if app.state.incidents_store is not None and incidents_store is None:
            app.state.incidents_store.close()  # only the store this lifespan itself built
        if app.state.history is not None:
            app.state.history.close()

    application = FastAPI(title="AttackTrace", version="0.1.0", lifespan=lifespan)
    application.state.hub = ws.Hub()
    application.state.settings = settings
    application.state.attack_limiter = RateLimiter(settings.attack_rate_per_min)
    if not settings.api_key:
        log.warning("AT_API_KEY is not set: POST /api/attack, /reset and /mode are open")
    application.state.reports_dir = settings.reports_dir
    application.state.hai_dir = settings.hai_dir
    application.state.mode = "sim"
    # Serializes /api/mode, /api/reset, /api/attack against each other: all three read or mutate
    # state.mode / active_runtime(state), and a reset or attack landing mid-mode-switch could
    # otherwise race (Expert Panel Review, SRE #5 -- the original mode_lock covered /api/mode
    # against itself only, not its neighbors).
    application.state.engine_lock = asyncio.Lock()
    application.state.hai = None
    application.state.live = None
    application.state.live_reason = None
    application.state.live_attacker = None
    application.state.history = None
    application.state.incidents_store = None
    application.state.operators = load_operators(settings)
    application.state.login_limiter = RateLimiter(10)  # login attempts per minute per client
    application.state.login_lockout = LoginLockout(
        settings.auth_lockout_threshold, settings.auth_lockout_s
    )
    if not settings.auth_secret:
        log.warning(
            "AT_AUTH_SECRET is not set: operator login is disabled, isolate trusts the "
            "client-supplied name (demo behavior)"
        )
    application.state.siem = (
        SiemNotifier(settings.siem_webhook_url, settings.siem_webhook_timeout_s)
        if settings.siem_webhook_url
        else None
    )
    application.state.ai_limiter = RateLimiter(settings.ai_rate_per_min)
    if not settings.ai_api_key:
        log.info("AT_AI_API_KEY is not set: Ask AI answers 503")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(rest.router)
    application.include_router(ws.router)
    return application


app = create_app()
