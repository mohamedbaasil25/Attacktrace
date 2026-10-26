import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Columns2, Radar, Waypoints, WifiOff } from "lucide-react";
import { Suspense, lazy } from "react";
import { CalibratingState } from "../components/ui/CalibratingState";
import { EmptyState } from "../components/ui/EmptyState";
import { IncidentToast } from "../components/ui/IncidentToast";
import { NoticeToast } from "../components/ui/NoticeToast";
import { Panel } from "../components/ui/Panel";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { AttackConsole } from "../features/console/AttackConsole";
import { IncidentPanel } from "../features/incident/IncidentPanel";
import { Timeline } from "../features/timeline/Timeline";
import { TwinView } from "../features/twin/TwinView";
import { useLive } from "../store/live";
import { useUi, type CenterView } from "../store/ui";
import { NavBar } from "./NavBar";
import { TopBar } from "./TopBar";
import { useLiveSourcePoll } from "./useLiveSourcePoll";
import { useLiveStream } from "./useLiveStream";

// Twin is the default view, loaded eagerly; Graph (@xyflow/react) and Split only pull their
// weight into the main bundle once the operator actually switches to them.
const GraphView = lazy(() =>
  import("../features/graph/GraphView").then((m) => ({ default: m.GraphView })),
);
const SplitView = lazy(() =>
  import("../features/split/SplitView").then((m) => ({ default: m.SplitView })),
);

function ViewToggle() {
  const view = useUi((s) => s.view);
  const setView = useUi((s) => s.setView);
  const hai = useLive((s) => s.latest?.mode === "hai");
  return (
    <SegmentedControl<CenterView>
      aria-label="View"
      layoutId="view-indicator"
      value={hai ? "graph" : view}
      onChange={setView}
      segments={[
        { value: "twin", label: "Twin", disabled: hai, title: hai ? "Twin is SIM only" : undefined },
        { value: "graph", label: "Graph" },
      ]}
    />
  );
}

function Center({ live }: { live: boolean }) {
  const chosen = useUi((s) => s.view);
  const hai = useLive((s) => s.latest?.mode === "hai");
  const view = hai ? "graph" : chosen; // a dataset replay has no twin
  const split = useUi((s) => s.split);
  // LIVE while recording a clean baseline and training: nothing to draw yet, just the progress.
  const calibrating = useLive(
    (s) => s.latest?.mode === "live" && s.status?.source?.state === "calibrating",
  );
  const progress = useLive((s) => s.status?.source?.progress ?? null);
  const reduce = useReducedMotion();
  const bodyKey = !live ? "no-signal" : calibrating ? "calibrating" : view;
  const body = (
    <AnimatePresence initial={false}>
      <motion.div
        key={bodyKey}
        className="absolute inset-0 h-full w-full"
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={reduce ? undefined : { opacity: 0 }}
        transition={{ duration: 0.2 }}
      >
        {!live ? (
          <EmptyState icon={WifiOff} text="No signal" />
        ) : calibrating ? (
          <CalibratingState progress={progress} />
        ) : view === "twin" ? (
          <TwinView />
        ) : (
          <Suspense fallback={null}>
            <GraphView />
          </Suspense>
        )}
      </motion.div>
    </AnimatePresence>
  );
  if (split) {
    return (
      <Panel title="Split view" icon={Columns2} actions={calibrating ? undefined : <ViewToggle />}>
        <div className="flex h-full flex-col">
          {/* Phase 14 C4: 42/58 (was 52/48) -- the mini-twin below needs more of the height
              budget to clear 12px; see geometry.ts's VIEW.h trim for the other half of the fix. */}
          <div className="h-[42%] shrink-0 border-b border-line-1">
            {live && !calibrating ? (
              <Suspense fallback={null}>
                <SplitView />
              </Suspense>
            ) : (
              <EmptyState icon={WifiOff} text="No signal" />
            )}
          </div>
          <div className="relative min-h-0 flex-1">{body}</div>
        </div>
      </Panel>
    );
  }
  return (
    <Panel
      title={view === "twin" ? "Digital twin" : "Process graph"}
      icon={view === "twin" ? Radar : Waypoints}
      actions={calibrating ? undefined : <ViewToggle />}
    >
      {body}
    </Panel>
  );
}

export function App() {
  useLiveStream();
  useLiveSourcePoll();
  const hasLatest = useLive((s) => s.latest !== null);
  const conn = useLive((s) => s.conn);
  const live = (conn === "live" || hasLatest) && hasLatest;

  return (
    // Below `lg` (1024px) the dashboard stacks into one scrolling column instead of clipping or
    // forcing horizontal scroll at a fixed 1280px floor; `lg`/`xl` reproduce the original fixed
    // 3-column, viewport-locked layout exactly (xl matches the pre-redesign 280/360px columns).
    <div className="flex min-h-screen flex-col overflow-y-auto bg-surface-0 lg:h-full lg:overflow-hidden">
      <NavBar />
      <div className="flex min-h-0 flex-1 flex-col gap-3 p-3 lg:gap-4 lg:overflow-hidden lg:p-4">
        <TopBar />
        <IncidentToast />
        <NoticeToast />
        <main className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[360px_420px_420px_220px] gap-3 lg:grid-cols-[240px_minmax(0,1fr)_320px] lg:grid-rows-[minmax(0,1fr)_168px] lg:gap-4 xl:grid-cols-[280px_minmax(0,1fr)_360px]">
          <AttackConsole />
          <Center live={live} />
          <IncidentPanel />
          <div className="min-h-0 lg:col-span-3">
            <Timeline />
          </div>
        </main>
      </div>
    </div>
  );
}
