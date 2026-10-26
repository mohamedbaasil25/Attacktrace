import { WifiOff } from "lucide-react";
import { useLiveSourcePoll } from "../../app/useLiveSourcePoll";
import { useLiveStream } from "../../app/useLiveStream";
import { NavBar } from "../../app/NavBar";
import { EmptyState } from "../../components/ui/EmptyState";
import { useLive } from "../../store/live";
import { AttackConsole } from "../console/AttackConsole";
import { Timeline } from "../timeline/Timeline";
import { TwinView } from "../twin/TwinView";

/** The scenario-launcher side of the dashboard, standalone: for working the simulator directly
 *  without the full incident/triage chrome. Same console, twin and timeline as Monitoring -- no
 *  separate "lab" data, since this project has only one simulated plant. */
export function LocalLabPage() {
  useLiveStream();
  useLiveSourcePoll();
  const hasLatest = useLive((s) => s.latest !== null);
  const conn = useLive((s) => s.conn);
  const live = (conn === "live" || hasLatest) && hasLatest;

  return (
    <div className="flex h-full min-w-[1280px] flex-col bg-surface-0">
      <NavBar />
      <main className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)] grid-rows-[minmax(0,1fr)_168px] gap-3 p-4">
        <div className="row-span-2">
          <AttackConsole />
        </div>
        <div className="relative min-h-0 overflow-hidden rounded-md border border-line-1 bg-surface-1">
          {live ? <TwinView /> : <EmptyState icon={WifiOff} text="No signal" />}
        </div>
        <div className="min-h-0">
          <Timeline />
        </div>
      </main>
    </div>
  );
}
