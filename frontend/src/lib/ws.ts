import type { LiveMessage } from "./types";

/** Validate a raw frame; returns null for anything that is not a well-formed live message. */
export function parseMessage(raw: unknown): LiveMessage | null {
  if (typeof raw !== "string") return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const m = data as Record<string, unknown>;
  if (typeof m.t !== "number" || (m.mode !== "sim" && m.mode !== "hai" && m.mode !== "live")) {
    return null;
  }
  if (!Array.isArray(m.nodes)) return null;
  for (const n of m.nodes) {
    if (typeof n !== "object" || n === null) return null;
    const node = n as Record<string, unknown>;
    if (typeof node.id !== "string" || typeof node.value !== "number") return null;
  }
  return data as LiveMessage;
}

export const BACKOFF_BASE_MS = 500;
export const BACKOFF_MAX_MS = 8000;

/** Exponential backoff: 500, 1000, 2000, 4000, 8000, 8000, ... */
export function backoffDelay(attempt: number): number {
  return Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** attempt);
}

export type ConnState = "connecting" | "live" | "reconnecting";

export interface LiveClientOptions {
  url: string;
  onMessage: (msg: LiveMessage) => void;
  onState: (state: ConnState) => void;
  /** Injectable for tests. */
  socketFactory?: (url: string) => WebSocket;
}

/** WebSocket client that reconnects forever with exponential backoff. Returns a closer. */
export function createLiveClient(opts: LiveClientOptions): () => void {
  const make = opts.socketFactory ?? ((u: string) => new WebSocket(u));
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let attempt = 0;
  let closed = false;

  const connect = () => {
    opts.onState(attempt === 0 ? "connecting" : "reconnecting");
    const ws = make(opts.url);
    socket = ws;
    ws.onopen = () => {
      if (closed) return;
      attempt = 0;
      opts.onState("live");
    };
    ws.onmessage = (ev: MessageEvent) => {
      const msg = parseMessage(ev.data);
      if (msg) opts.onMessage(msg);
    };
    ws.onclose = () => {
      if (closed) return;
      opts.onState("reconnecting");
      timer = setTimeout(connect, backoffDelay(attempt));
      attempt += 1;
    };
    ws.onerror = () => ws.close();
  };

  connect();
  return () => {
    closed = true;
    clearTimeout(timer);
    if (socket?.readyState === WebSocket.CONNECTING) {
      socket.onopen = () => socket?.close(); // closing mid-handshake would log a browser warning
    } else {
      socket?.close();
    }
  };
}

export function liveUrl(loc: Pick<Location, "protocol" | "host">): string {
  return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/ws/live`;
}
