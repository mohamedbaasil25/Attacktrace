import type {
  AttackRequest,
  AttackResponse,
  HistorySample,
  IsolateRequest,
  IsolateResponse,
  LoginResponse,
  Mode,
  Status,
  TagHealth,
  Topology,
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

const post = <T>(path: string, body?: unknown): Promise<T> =>
  json<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json", ...(KEY ? { "x-api-key": KEY } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const getStatus = (): Promise<Status> => json<Status>("/api/status");
/** Per-tag LIVE quality and age; 404 when LIVE is not configured. */
export const getLiveHealth = (): Promise<TagHealth[]> => json<TagHealth[]>("/api/live/health");
export const getTopology = (): Promise<Topology> => json<Topology>("/api/topology");
export const setMode = (mode: Mode): Promise<Status> => post<Status>("/api/mode", { mode });
export const postAttack = (req: AttackRequest): Promise<AttackResponse> =>
  post<AttackResponse>("/api/attack", req);
export const postReset = (): Promise<Status> => post<Status>("/api/reset");
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
 *  is a unix-seconds lower bound; omitted = the historian's full retention window. */
export const getHistory = (node: string, sinceS?: number): Promise<HistorySample[]> =>
  json<HistorySample[]>(
    `/api/history?${new URLSearchParams({
      node,
      ...(sinceS !== undefined ? { since: String(sinceS) } : {}),
    }).toString()}`,
  );
