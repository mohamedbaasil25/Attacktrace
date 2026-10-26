import type {
  AttackRequest,
  AttackResponse,
  HistorySample,
  Incident,
  IsolateRequest,
  IsolateResponse,
  LoginResponse,
  Mode,
  Status,
  TagHealth,
  Topology,
  VerifyLedgerResponse,
} from "./types";

/** Demo key for the write endpoints. It is bundled into the build, so it deters misuse of an
 *  exposed demo; it is not user authentication. Empty = the server leaves writes open. */
const KEY: string = (import.meta.env.VITE_API_KEY as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
  /** 401 (missing/wrong key) or 403 (demo mode off). */
  get locked(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep the status code */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

/** `authToken`: the operator's session token (`useAuth`), attached when present -- required by
 *  the server (Phase 5.3) once AT_AUTH_SECRET is configured, since the demo key alone (`KEY`
 *  above) is visible to every browser user and is not authentication. Without a configured
 *  AT_AUTH_SECRET server-side, the server ignores this header entirely and the demo key alone
 *  still works, exactly as before Phase 5.3. */
const post = <T>(path: string, body?: unknown, authToken?: string): Promise<T> =>
  json<T>(path, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(KEY ? { "x-api-key": KEY } : {}),
      ...(authToken ? { authorization: `Bearer ${authToken}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

/** GET with the operator's session token attached when present -- same rationale as `post`
 *  above: required once AT_AUTH_SECRET is configured, ignored otherwise. */
const getAuthed = <T>(path: string, authToken?: string): Promise<T> =>
  json<T>(path, authToken ? { headers: { authorization: `Bearer ${authToken}` } } : undefined);

/** POST gated like a read endpoint (login once AT_AUTH_SECRET is configured; no demo key) --
 *  for /api/ai/ask, which reads data but never mutates plant state. */
const postAuthed = <T>(path: string, body: unknown, authToken?: string): Promise<T> =>
  json<T>(path, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(authToken ? { authorization: `Bearer ${authToken}` } : {}),
    },
    body: JSON.stringify(body),
  });

export const getStatus = (): Promise<Status> => json<Status>("/api/status");
/** Per-tag LIVE quality and age; 404 when LIVE is not configured. */
export const getLiveHealth = (authToken?: string): Promise<TagHealth[]> =>
  getAuthed<TagHealth[]>("/api/live/health", authToken);
export const getTopology = (): Promise<Topology> => json<Topology>("/api/topology");
/** Newest-first; requires login once AT_AUTH_SECRET is configured. */
export const getIncidents = (authToken?: string): Promise<Incident[]> =>
  getAuthed<Incident[]>("/api/incidents", authToken);
/** Audit-ledger hash-chain integrity; requires login once AT_AUTH_SECRET is configured. */
export const getEvidenceVerification = (authToken?: string): Promise<VerifyLedgerResponse> =>
  getAuthed<VerifyLedgerResponse>("/api/evidence/verify", authToken);
export const setMode = (mode: Mode, authToken?: string): Promise<Status> =>
  post<Status>("/api/mode", { mode }, authToken);
export const postAttack = (req: AttackRequest, authToken?: string): Promise<AttackResponse> =>
  post<AttackResponse>("/api/attack", req, authToken);
export const postReset = (authToken?: string): Promise<Status> =>
  post<Status>("/api/reset", undefined, authToken);
/** `authToken`: the operator's session token (`useAuth`), attached when AT_AUTH_SECRET is
 *  configured server-side. Without one, the server falls back to trusting `req.operator`. */
export const postIsolate = (req: IsolateRequest, authToken?: string): Promise<IsolateResponse> =>
  json<IsolateResponse>("/api/isolate", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(KEY ? { "x-api-key": KEY } : {}),
      ...(authToken ? { authorization: `Bearer ${authToken}` } : {}),
    },
    body: JSON.stringify(req),
  });
export const reportUrl = (incidentId: string): string =>
  `/api/incidents/${encodeURIComponent(incidentId)}/report.pdf`;
export const postLogin = (username: string, password: string): Promise<LoginResponse> =>
  post<LoginResponse>("/api/auth/login", { username, password });
/** Retained samples for one node, beyond the 5-minute ring buffer (GET /api/history). `sinceS`
 *  is a unix-seconds lower bound; omitted = the historian's full retention window. Requires
 *  login once AT_AUTH_SECRET is configured, same as `getIncidents`/`getLiveHealth`. */
export const getHistory = (
  node: string,
  sinceS?: number,
  authToken?: string,
): Promise<HistorySample[]> =>
  getAuthed<HistorySample[]>(
    `/api/history?${new URLSearchParams({
      node,
      ...(sinceS !== undefined ? { since: String(sinceS) } : {}),
    }).toString()}`,
    authToken,
  );
/** Ask AI: a real LLM call, grounded in this session's own incident data server-side (app/ai.py
 *  in the backend). 503 when AT_AI_API_KEY is not configured, 502 if the model call itself fails,
 *  429 if rate-limited -- all surfaced to the caller as a normal `ApiError`. */
export const postAskAi = (question: string, authToken?: string): Promise<{ answer: string }> =>
  postAuthed<{ answer: string }>("/api/ai/ask", { question }, authToken);
