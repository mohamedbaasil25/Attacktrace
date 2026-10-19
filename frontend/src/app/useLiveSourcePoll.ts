import { useEffect } from "react";
import { getLiveHealth, getStatus } from "../lib/api";
import { useLive } from "../store/live";

const POLL_MS = 2000;

/** While LIVE is the active mode, refreshes source health (`/api/status`) and per-tag quality
 *  (`/api/live/health`) on a light poll. The WebSocket stream already carries node values. */
export function useLiveSourcePoll(): void {
  const mode = useLive((s) => s.latest?.mode);
  const setStatus = useLive((s) => s.setStatus);
  const setLiveHealth = useLive((s) => s.setLiveHealth);

  useEffect(() => {
    if (mode !== "live") return;
    let cancelled = false;
    const poll = (): void => {
      getStatus().then((s) => !cancelled && setStatus(s)).catch(() => undefined);
      getLiveHealth().then((h) => !cancelled && setLiveHealth(h)).catch(() => undefined);
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [mode, setStatus, setLiveHealth]);
}
