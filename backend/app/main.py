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
from app.api.security import RateLimiter
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
from app.graph import load_graph
from app.history import HistoryStore
from app.live.runtime import LiveRuntime, build_live_runtime
from app.siem import SiemNotifier

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


def build_hai_engine(settings: Settings) -> HaiEngine | None:
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
        return HaiEngine(load_hai_detector(d), load_hai_baseline(d), replay, settings)
    except Exception:
        log.exception("HAI mode unavailable")
        return None


def build_engine(settings: Settings) -> Engine:
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
    )


def create_app(
    engine: Engine | None = None,
    run_loop: bool = True,
    hai_engine: HaiEngine | None = None,
    live_runtime: LiveRuntime | None = None,
    history: HistoryStore | None = None,
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine or await asyncio.to_thread(build_engine, settings)
        app.state.hai = hai_engine
        if hai_engine is None and engine is None:  # production start: look for HAI data too
            app.state.hai = await asyncio.to_thread(build_hai_engine, settings)
        if live_runtime is not None:
            app.state.live = live_runtime
        elif engine is None:  # production start: LIVE is optional and never blocks SIM or HAI
            app.state.live, app.state.live_reason = build_live_runtime(settings)
        if app.state.live is not None:
            app.state.live_attacker = LiveAttackLauncher(settings.attacker_allowlist)
            await app.state.live.source.start()
        if history is not None:
            app.state.history = history
        elif engine is None:  # production start only: same convention as LIVE above
            app.state.history = HistoryStore(settings.history_db)
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
    application.state.hai = None
    application.state.live = None
    application.state.live_reason = None
    application.state.live_attacker = None
    application.state.history = None
    application.state.operators = load_operators(settings)
    application.state.login_limiter = RateLimiter(10)  # login attempts per minute per client
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
