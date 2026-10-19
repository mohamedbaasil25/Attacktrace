import { useEffect } from "react";
import { getStatus, getTopology } from "../lib/api";
import { createLiveClient, liveUrl } from "../lib/ws";
import { useLive } from "../store/live";

/** Connects the WebSocket once, feeds the store, and refreshes REST state on (re)connect. */
export function useLiveStream(): void {
  useEffect(() => {
    const { push, setConn, setStatus, setTopology } = useLive.getState();
    const close = createLiveClient({
      url: liveUrl(window.location),
      onMessage: (m) => push(m),
      onState: (state) => {
        setConn(state);
        if (state !== "live") return;
        getStatus().then(setStatus, () => undefined);
        getTopology().then(setTopology, () => undefined);
      },
    });
    return close;
  }, []);
}
