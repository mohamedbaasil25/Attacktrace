import { useEffect } from "react";
import { getStatus, getTopology } from "../lib/api";
import { createLiveClient, liveUrl } from "../lib/ws";
import { useAuth } from "../store/auth";
import { useLive } from "../store/live";

/** Connects the WebSocket, feeds the store, and refreshes REST state on (re)connect. Reconnects
 *  whenever the operator token changes (login/logout): the token travels in the connection URL
 *  (a browser's native WebSocket API can't set a custom header), so a stale connection would
 *  otherwise keep an old session's credentials past logout.
 *
 *  `/api/status` and `/api/topology` are fetched unconditionally on mount, NOT only once the
 *  socket reaches "live" -- both stay open even when AT_AUTH_SECRET is configured and no one is
 *  logged in yet (deliberately: the mode toggle, and the login prompt itself, need to know
 *  `auth_required`/`hai_available`/`live_available` before any session exists). Gating this behind
 *  the WS connection state would leave the whole top bar looking broken (mode toggle stuck
 *  disabled with a misleading "data missing" reason) for exactly the logged-out case the login
 *  flow needs to handle gracefully. The WS-connect refresh below still runs too, to pick up
 *  changes another client made while this one was offline. */
export function useLiveStream(): void {
  const authToken = useAuth((s) => s.token);
  useEffect(() => {
    const { push, setConn, setStatus, setTopology } = useLive.getState();
    getStatus().then(setStatus, () => undefined);
    getTopology().then(setTopology, () => undefined);
    const close = createLiveClient({
      url: liveUrl(window.location, authToken || undefined),
      onMessage: (m) => push(m),
      onState: (state) => {
        setConn(state);
        if (state !== "live") return;
        getStatus().then(setStatus, () => undefined);
        getTopology().then(setTopology, () => undefined);
      },
    });
    return close;
  }, [authToken]);
}
