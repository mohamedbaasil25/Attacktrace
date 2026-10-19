import { lazy, Suspense } from "react";
import { App } from "./App";

// Tiny pathname switch instead of a router dependency. The metrics page (and ECharts) load lazily.
const MetricsPage = lazy(() =>
  import("../features/metrics/MetricsPage").then((m) => ({ default: m.MetricsPage })),
);

export function Root() {
  if (window.location.pathname.replace(/\/$/, "") === "/metrics") {
    return (
      <Suspense fallback={null}>
        <MetricsPage />
      </Suspense>
    );
  }
  return <App />;
}
