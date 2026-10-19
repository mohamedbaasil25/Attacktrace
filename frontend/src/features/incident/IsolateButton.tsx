import { LoaderCircle, ShieldCheck, TriangleAlert, Unplug } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, postIsolate } from "../../lib/api";
import {
  IDLE,
  advance,
  begin,
  candidateFor,
  disabledReason,
  refused,
  type IsoState,
} from "../../lib/isolate";
import type { Incident } from "../../lib/types";
import { useAuth } from "../../store/auth";
import { useLive } from "../../store/live";
import { noticeIfLocked, useUi } from "../../store/ui";

/** Isolate the best candidate not tried yet. Containment is read from the incident, never assumed:
 *  idle -> pending -> Contained (green, with time) or Not contained (amber, offers the next one). */
export function IsolateButton({ incident }: { incident: Incident }) {
  const hai = useLive((s) => s.latest?.mode === "hai");
  const live = useLive((s) => s.latest?.mode === "live");
  const replaying = useLive((s) => s.cursor !== null);
  const operatorName = useUi((s) => s.operatorName);
  const authToken = useAuth((s) => s.token);
  const [iso, setIso] = useState<IsoState>(IDLE);

  // Messages arrive twice a second; each one is a chance for pending to resolve or time out.
  useEffect(() => {
    setIso((s) => advance(s, incident, Date.now()));
  }, [incident]);

  const tried = iso.incidentId === incident.id ? iso.tried : [];
  const next = candidateFor(incident, tried);
  // A verified login (Production Transition Roadmap, Phase 1) identifies the operator just as
  // well as the free-text name field -- the server prefers the token identity either way.
  const operatorSet = operatorName.trim().length > 0 || authToken.length > 0;
  const reason = disabledReason(incident, { hai, live, replaying, operatorSet });

  const click = async () => {
    if (!next) return;
    try {
      const r = await postIsolate(
        { incident_id: incident.id, node_id: next, operator: operatorName },
        authToken || undefined,
      );
      setIso((s) =>
        r.accepted ? begin(s, incident, next, Date.now()) : refused(s, r.reason ?? "Refused"),
      );
    } catch (e) {
      if (!noticeIfLocked(e)) setIso((s) => refused(s, e instanceof ApiError ? e.message : "Failed"));
    }
  };

  if (iso.phase === "contained") {
    return (
      <div
        role="status"
        data-testid="isolate-state"
        className="flex items-center gap-2 text-xs text-normal"
      >
        <ShieldCheck size={14} aria-hidden />
        <span className="font-medium">Contained</span>
        <span className="font-mono text-ink-2">
          {iso.node}
          {iso.seconds !== null ? ` · ${iso.seconds.toFixed(0)} s` : ""}
          {incident.isolated_by ? ` · by ${incident.isolated_by}` : ""}
        </span>
      </div>
    );
  }
  if (iso.phase === "pending") {
    return (
      <button
        type="button"
        disabled
        data-testid="isolate-state"
        className="flex h-8 items-center gap-1 rounded bg-accent px-3 text-xs font-medium text-bg opacity-70"
      >
        <LoaderCircle size={14} className="animate-spin" aria-hidden />
        Isolating {iso.node}
      </button>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      {iso.phase === "failed" && (
        <div
          role="status"
          data-testid="isolate-state"
          className="flex items-center gap-1 text-xs text-affected"
        >
          <TriangleAlert size={14} aria-hidden />
          <span className="font-medium">Not contained</span>
          <span className="font-mono text-ink-2">{iso.node}</span>
        </div>
      )}
      <button
        type="button"
        onClick={() => void click()}
        disabled={reason !== null || next === null}
        title={reason ?? undefined}
        className="flex h-8 w-fit items-center gap-1 rounded bg-accent px-3 text-xs font-medium text-bg transition-opacity duration-150 hover:opacity-90 disabled:opacity-50"
      >
        <Unplug size={14} aria-hidden />
        {next ? `Isolate ${next}` : "No candidate"}
      </button>
      {iso.note && <span className="text-xs text-ink-2">{iso.note}</span>}
    </div>
  );
}
