import { Crosshair, Database, Rocket, RotateCcw, WifiOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "../../components/ui/Button";
import { Chip } from "../../components/ui/Chip";
import { Disclosure } from "../../components/ui/Disclosure";
import { EmptyState } from "../../components/ui/EmptyState";
import { Panel } from "../../components/ui/Panel";
import { postAttack, postReset } from "../../lib/api";
import { SCENARIOS, magnitudeFor, validTargets } from "../../lib/scenarios";
import type { Scenario } from "../../lib/types";
import { useLive } from "../../store/live";
import { noticeIfLocked } from "../../store/ui";
import { MagnitudeField } from "./MagnitudeField";
import { NodeScores } from "./NodeScores";
import { ScenarioPicker } from "./ScenarioPicker";

const field = "h-8 rounded border border-line-1 bg-surface-0 px-2 font-mono text-xs text-ink-1";

export function AttackConsole() {
  const conn = useLive((s) => s.conn);
  const topology = useLive((s) => s.topology);
  const clear = useLive((s) => s.clear);
  const hai = useLive((s) => s.latest?.mode === "hai");
  const [scenario, setScenario] = useState<Scenario>("sensor_offset");
  const [target, setTarget] = useState("LIT101");
  const [magnitude, setMagnitude] = useState(0);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; error: boolean } | null>(null);

  const targets = useMemo(() => validTargets(scenario, topology?.nodes ?? []), [scenario, topology]);
  const node = targets.find((n) => n.id === target) ?? targets[0];
  const input = useMemo(() => magnitudeFor(scenario, node), [scenario, node]);

  useEffect(() => {
    if (node && node.id !== target) setTarget(node.id);
  }, [node, target]);
  useEffect(() => {
    setMagnitude(input.kind === "none" ? 0 : input.value);
  }, [input]);

  const launch = async () => {
    if (!node) return;
    setBusy(true);
    try {
      const r = await postAttack({ scenario, target: node.id, magnitude });
      setNote({ text: r.attack_id, error: false });
    } catch (e) {
      if (!noticeIfLocked(e)) setNote({ text: e instanceof Error ? e.message : "Failed", error: true });
    } finally {
      setBusy(false);
    }
  };
  const reset = async () => {
    await postReset().catch((e: unknown) => noticeIfLocked(e));
    clear();
    setNote(null);
  };

  const ready = conn === "live" && topology !== null;
  if (ready && hai) {
    return (
      <Panel title="Replay" icon={Database}>
        <div className="flex h-full flex-col">
          <div className="min-h-0 flex-1">
            <EmptyState icon={Database} text="HAI dataset" />
          </div>
          <Button
            variant="secondary"
            onClick={() => void reset()}
            icon={<RotateCcw size={14} aria-hidden />}
            className="m-2"
          >
            Restart
          </Button>
        </div>
      </Panel>
    );
  }
  return (
    <Panel title="Attack console" icon={Crosshair}>
      {!ready ? (
        <EmptyState icon={WifiOff} text="No signal" />
      ) : (
        <form
          className="flex h-full flex-col gap-3 overflow-y-auto p-2"
          onSubmit={(e) => {
            e.preventDefault();
            void launch();
          }}
        >
          {conn === "live" && (
            <Chip tone="accent" title="Real Modbus TCP against our own emulated plant">
              Emulated plant
            </Chip>
          )}
          <ScenarioPicker scenarios={SCENARIOS} value={scenario} onChange={setScenario} />
          <Button type="submit" variant="primary" loading={busy} disabled={!node} icon={<Rocket size={14} aria-hidden />}>
            Launch
          </Button>
          <Button type="button" variant="secondary" onClick={() => void reset()} icon={<RotateCcw size={14} aria-hidden />}>
            Reset
          </Button>
          {note && (
            <span
              role="status"
              className={`font-mono text-xs ${note.error ? "text-origin" : "text-normal"}`}
            >
              {note.text}
            </span>
          )}
          <Disclosure label="Advanced">
            <label className="flex flex-col gap-1 text-xs text-ink-3">
              Target
              <select className={field} value={node?.id ?? ""} onChange={(e) => setTarget(e.target.value)}>
                {targets.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.id}
                  </option>
                ))}
              </select>
            </label>
            <MagnitudeField input={input} value={magnitude} onChange={setMagnitude} className={field} />
            <NodeScores />
          </Disclosure>
        </form>
      )}
    </Panel>
  );
}
