import { Cpu, FileX, Gauge, LoaderCircle, Sliders } from "lucide-react";
import { useEffect, useState } from "react";
import { NavBar } from "../../app/NavBar";
import { Chip } from "../../components/ui/Chip";
import { EmptyState } from "../../components/ui/EmptyState";
import { getStatus, getTopology } from "../../lib/api";
import type { NodeKind, Status, Topology } from "../../lib/types";

type Load = { state: "loading" } | { state: "error" } | { state: "ready"; topology: Topology; status: Status };

const KIND_ICON: Record<NodeKind, typeof Cpu> = {
  sensor: Gauge,
  actuator: Sliders,
  controller: Cpu,
};

const KIND_LABEL: Record<NodeKind, string> = {
  sensor: "Sensor",
  actuator: "Actuator",
  controller: "Controller",
};

export function AssetsPage() {
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    let live = true;
    Promise.all([getTopology(), getStatus()])
      .then(([topology, status]) => live && setLoad({ state: "ready", topology, status }))
      .catch(() => live && setLoad({ state: "error" }));
    return () => {
      live = false;
    };
  }, []);

  return (
    <div className="flex h-full min-w-[1024px] flex-col bg-surface-0">
      <NavBar />
      <main className="flex min-h-0 flex-1 flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <h1 className="text-title font-semibold tracking-tight text-ink-1">Assets</h1>
          {load.state === "ready" && (
            <Chip tone="neutral">
              {load.topology.nodes.length} nodes · {load.status.mode.toUpperCase()} mode
            </Chip>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {load.state === "loading" && <EmptyState icon={LoaderCircle} text="Loading" />}
          {load.state === "error" && <EmptyState icon={FileX} text="Could not load" />}
          {load.state === "ready" && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
              {load.topology.nodes.map((n) => {
                const Icon = KIND_ICON[n.type];
                return (
                  <div
                    key={n.id}
                    className="flex flex-col gap-2 rounded-md border border-line-1 bg-surface-1 p-3"
                  >
                    <div className="flex items-center gap-2 text-ink-1">
                      <Icon size={16} aria-hidden />
                      <span className="font-mono text-sm font-medium">{n.id}</span>
                    </div>
                    <span className="text-label text-ink-2">{n.label}</span>
                    <div className="mt-auto flex items-center justify-between font-mono text-caption text-ink-3">
                      <span>{KIND_LABEL[n.type]}</span>
                      <span>
                        {n.lo}–{n.hi} {n.unit}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
