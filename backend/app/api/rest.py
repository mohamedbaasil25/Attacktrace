"""REST endpoints (§5.9). The engine lives on `app.state.engine`."""

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.ai import AiNotConfiguredError, AiRequestFailedError, build_context, generate_answer
from app.api.auth import Operator, authenticated_operator, issue_token, verify_password
from app.api.security import (
    _is_loopback,
    limit_ai,
    limit_attacks,
    require_demo,
    require_key,
    require_operator_when_configured,
    require_read_access_when_configured,
)
from app.data.hai import hai_paths
from app.engine import Engine
from app.report import render_report
from app.runtime import Runtime, active_runtime
from app.schemas import (
    AskAiRequest,
    AskAiResponse,
    AttackRequest,
    AttackResponse,
    HistorySample,
    Incident,
    IsolateRequest,
    IsolateResponse,
    LoginRequest,
    LoginResponse,
    ModeRequest,
    SourceInfo,
    Status,
    TagHealth,
    Topology,
    VerificationIssueOut,
    VerifyLedgerResponse,
)

router = APIRouter(prefix="/api")


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def _session_false_alarm_per_hour(rt: Runtime) -> float:
    """Incidents with no ground truth, over elapsed session hours. HAI incidents always have no
    ground truth by design (it isn't exposed the way SIM/LIVE's launched-attack truth is), so this
    is only meaningful for SIM and LIVE -- callers gate on `rt.mode` before using it."""
    hours = rt.uptime_s / 3600.0
    if hours <= 0:
        return 0.0
    false_alarms = sum(1 for inc in rt.incidents if inc.ground_truth is None)
    return false_alarms / hours


def _live_availability(state: Any) -> tuple[bool, str | None]:
    live = getattr(state, "live", None)
    if live is None:
        return False, getattr(state, "live_reason", None) or "LIVE is not configured"
    ok, reason = live.available()
    return bool(ok), reason


def _source(state: Any) -> SourceInfo:
    """Where the active mode gets its data and how healthy that link is."""
    if state.mode == "live" and getattr(state, "live", None) is not None:
        info: SourceInfo = state.live.source_info()
        return info
    if state.mode == "hai":
        return SourceInfo(mode="hai", connected=True, protocol="replay", state="connected")
    return SourceInfo(mode="sim", connected=True, protocol="internal", state="connected")


def _status(request: Request) -> Status:
    state = request.app.state
    rt = active_runtime(state)
    live_ok, live_reason = _live_availability(state)
    return Status(
        mode=state.mode,
        hai_available=bool(hai_paths(state.hai_dir)),
        detector_active=rt.detector_kind,
        uptime_s=rt.uptime_s,
        source=_source(state),
        live_available=live_ok,
        live_reason=live_reason,
        auth_required=bool(state.settings.auth_secret),
        evidence_available=getattr(state, "incidents_store", None) is not None,
    )


@router.get("/status")
def get_status(request: Request) -> Status:
    return _status(request)


@router.post(
    "/mode", dependencies=[Depends(require_key), Depends(require_operator_when_configured)]
)
async def set_mode(body: ModeRequest, request: Request) -> Status:
    state = request.app.state
    async with state.engine_lock:
        if body.mode == "hai":
            if not hai_paths(state.hai_dir):
                raise HTTPException(status_code=409, detail="HAI data not available")
            if state.hai is None:
                raise HTTPException(status_code=503, detail="HAI models not ready")
            if state.mode != "hai":
                state.hai.reset()  # every switch starts the replay from its beginning
        if body.mode == "live":
            ok, reason = _live_availability(state)
            if not ok:
                raise HTTPException(status_code=409, detail=f"LIVE unavailable: {reason}")
        state.mode = body.mode
        return _status(request)


@router.get("/topology")
def get_topology(request: Request) -> Topology:
    return active_runtime(request.app.state).topology()


@router.post(
    "/attack",
    dependencies=[
        Depends(require_key),
        Depends(require_operator_when_configured),
        Depends(require_demo),
        Depends(limit_attacks),
    ],
)
async def post_attack(body: AttackRequest, request: Request) -> AttackResponse:
    async with request.app.state.engine_lock:
        if request.app.state.mode == "hai":
            raise HTTPException(status_code=409, detail="HAI attacks come from the dataset")
        try:
            if request.app.state.mode == "live":  # never the simulator's engine
                launcher = request.app.state.live_attacker
                attack_id = await launcher.launch(request.app.state.live, body)
                return AttackResponse(attack_id=attack_id)
            return AttackResponse(attack_id=_engine(request).launch(body))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/isolate", dependencies=[Depends(require_key)], response_model=IsolateResponse)
def post_isolate(body: IsolateRequest, request: Request) -> IsolateResponse | JSONResponse:
    if request.app.state.mode == "live":  # advisory only: AttackTrace never writes to the plant
        inc = next(
            (i for i in active_runtime(request.app.state).incidents if i.id == body.incident_id),
            None,
        )
        store = getattr(request.app.state, "incidents_store", None)
        if store is not None:  # an attempted isolate is security-relevant even when blocked
            store.ledger.append(
                "isolation_outcome",
                body.incident_id,
                {
                    "node_id": body.node_id,
                    "accepted": False,
                    "reason": "live-read-only",
                    "operator": body.operator,
                },
            )
        return JSONResponse(
            status_code=409,
            content={
                "detail": "live-read-only",
                "accepted": False,
                "reason": "live-read-only",
                "advice": inc.action if inc else "Isolate the node at the plant, not from here",
            },
        )
    if request.app.state.mode == "hai":
        raise HTTPException(
            status_code=409, detail="Isolation is not available in HAI mode: the data is a replay"
        )
    operator_name = body.operator
    settings = request.app.state.settings
    if settings.auth_secret:  # auth configured: require a real identity
        op = authenticated_operator(request)
        if op is None:
            raise HTTPException(status_code=401, detail="Login required to isolate")
        if op.role != "operator":
            raise HTTPException(status_code=403, detail="Analyst role cannot isolate")
        operator_name = op.username  # the verified identity, never the client-supplied field
    elif not (_is_loopback(settings.host) and settings.demo_mode):
        # No real auth configured, and this is not loopback-only local demo: fail closed rather
        # than silently trust the client-supplied operator-name field for the one write action
        # with a real safety-relevant effect. Mirrors `require_key`'s existing "fail closed
        # outside loopback dev" rule for AT_API_KEY (app/api/security.py), applied to
        # AT_AUTH_SECRET too -- that rule never covered this fallback, which is a production gap.
        raise HTTPException(
            status_code=503,
            detail="AT_AUTH_SECRET is not set and this server is not loopback-only local "
            "development (AT_HOST is not loopback, or AT_DEMO_MODE is off): isolate fails "
            "closed rather than trust the client-supplied operator name. Set AT_AUTH_SECRET to "
            "enable real operator login.",
        )
    accepted, reason = _engine(request).isolate(body.incident_id, body.node_id, operator_name)
    return IsolateResponse(accepted=accepted, reason=reason)


@router.post("/auth/login")
def post_login(body: LoginRequest, request: Request) -> LoginResponse:
    settings = request.app.state.settings
    if not settings.auth_secret:
        raise HTTPException(status_code=503, detail="Operator auth is not configured")
    client = request.client.host if request.client else "unknown"
    wait = request.app.state.login_limiter.check(client)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts, slow down",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    lockout = request.app.state.login_lockout
    locked_for = lockout.check(body.username)
    if locked_for is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts for this account, try again later",
            headers={"Retry-After": str(int(locked_for) + 1)},
        )
    cred = request.app.state.operators.get(body.username)
    if cred is None or not verify_password(body.password, cred.password_hash):
        lockout.record_failure(body.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    lockout.record_success(body.username)
    token = issue_token(
        Operator(body.username, cred.role), settings.auth_secret, settings.auth_token_ttl_s
    )
    return LoginResponse(
        token=token, username=body.username, role=cred.role, expires_in_s=settings.auth_token_ttl_s
    )


@router.get("/history", dependencies=[Depends(require_read_access_when_configured)])
def get_history(
    node: str, request: Request, since: float | None = None, until: float | None = None
) -> list[HistorySample]:
    store = getattr(request.app.state, "history", None)
    if store is None:
        raise HTTPException(status_code=404, detail="Historian not configured")
    return [
        HistorySample(t=s.t, value=s.value, score=s.score, status=s.status)
        for s in store.query(node, since, until)
    ]


@router.get("/evidence/verify")
def get_evidence_verification(request: Request) -> VerifyLedgerResponse:
    """Phase 3: walks the audit ledger's hash chain and reports whether it is intact. Requires a
    login when the server has real auth configured (same gate as isolate, Phase 1) -- this exposes
    forensic detail (first failing sequence, event kind) and should not be open to anyone who can
    merely reach the API. Never a bare HTTP 200 == "verified": `status` in the body is what a
    caller must branch on, not the status code."""
    settings = request.app.state.settings
    if settings.auth_secret and authenticated_operator(request) is None:
        raise HTTPException(status_code=401, detail="Login required to verify evidence")
    store = getattr(request.app.state, "incidents_store", None)
    if store is None:
        raise HTTPException(status_code=404, detail="Evidence store not configured")
    result = store.ledger.verify()
    return VerifyLedgerResponse(
        status=result.status,
        checked=result.checked,
        first_failure=VerificationIssueOut(
            seq=result.first_failure.seq,
            kind=result.first_failure.kind,
            detail=result.first_failure.detail,
        )
        if result.first_failure
        else None,
        issue_count=len(result.issues),
    )


@router.post(
    "/reset", dependencies=[Depends(require_key), Depends(require_operator_when_configured)]
)
async def post_reset(request: Request) -> Status:
    async with request.app.state.engine_lock:
        active_runtime(request.app.state).reset()
        return _status(request)


@router.get("/live/health", dependencies=[Depends(require_read_access_when_configured)])
def get_live_health(request: Request) -> list[TagHealth]:
    live = getattr(request.app.state, "live", None)
    if live is None:
        reason = getattr(request.app.state, "live_reason", None) or "LIVE is not configured"
        raise HTTPException(status_code=404, detail=reason)
    health: list[TagHealth] = live.health()
    return health


@router.get("/incidents", dependencies=[Depends(require_read_access_when_configured)])
def get_incidents(request: Request) -> list[Incident]:
    return list(reversed(active_runtime(request.app.state).incidents))  # newest first


@router.get(
    "/incidents/{incident_id}/report.pdf",
    dependencies=[Depends(require_read_access_when_configured)],
)
def get_incident_report(incident_id: str, request: Request) -> Response:
    rt = active_runtime(request.app.state)
    inc = next((i for i in rt.incidents if i.id == incident_id), None)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    impact = getattr(rt, "incident_impact", {}).get(incident_id)
    pdf = render_report(inc, impact, rt.mode, time.time())
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{incident_id}_report.pdf"'},
    )


@router.post(
    "/ai/ask",
    dependencies=[Depends(require_read_access_when_configured), Depends(limit_ai)],
)
def post_ask_ai(body: AskAiRequest, request: Request) -> AskAiResponse:
    """Free-text Q&A, strictly grounded in this session's own incident data (app/ai.py). Gated
    like the other read endpoints (login required once AT_AUTH_SECRET is configured), plus its
    own rate limit (`limit_ai`) since -- unlike every other endpoint here -- it makes a real,
    billed external API call."""
    settings = request.app.state.settings
    rt = active_runtime(request.app.state)
    context = build_context(rt)
    try:
        answer = generate_answer(body.question, context, settings)
    except AiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503, detail="Ask AI is not configured (AT_AI_API_KEY is not set)"
        ) from exc
    except AiRequestFailedError as exc:
        raise HTTPException(status_code=502, detail="Ask AI request failed, try again") from exc
    return AskAiResponse(answer=answer)


@router.get("/metrics", dependencies=[Depends(require_read_access_when_configured)])
def get_metrics(request: Request) -> dict[str, Any]:
    reports_dir = request.app.state.reports_dir
    path = reports_dir / "metrics.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="metrics.json not found; run `make eval`")
    data: dict[str, Any] = json.loads(path.read_text())
    # Phase 13 Part F: merged in at response time, never written into metrics.json itself.
    live_path = reports_dir / "live_metrics.json"
    if live_path.exists():
        data["live"] = json.loads(live_path.read_text())
    # Current running session's own false-alarm rate, vs. the documented baseline above -- SIM and
    # LIVE only (HAI incidents carry no ground truth by design, so the heuristic doesn't apply).
    rt = active_runtime(request.app.state)
    if rt.mode in ("sim", "live"):
        data["live_session"] = {
            "mode": rt.mode,
            "uptime_s": rt.uptime_s,
            "false_alarm_per_hour": _session_false_alarm_per_hour(rt),
        }
    return data
