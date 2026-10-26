import { lazy, Suspense } from "react";
import type { LazyExoticComponent } from "react";
import { App } from "./App";
import { normalizePath } from "./nav";

// Tiny pathname switch instead of a router dependency. Each page below is its own full browser
// navigation (not a client route), lazy-loaded so the main dashboard bundle doesn't grow.
const MetricsPage = lazy(() =>
  import("../features/metrics/MetricsPage").then((m) => ({ default: m.MetricsPage })),
);
const AlertsPage = lazy(() =>
  import("../features/alerts/AlertsPage").then((m) => ({ default: m.AlertsPage })),
);
const AssetsPage = lazy(() =>
  import("../features/assets/AssetsPage").then((m) => ({ default: m.AssetsPage })),
);
const SourcesPage = lazy(() =>
  import("../features/sources/SourcesPage").then((m) => ({ default: m.SourcesPage })),
);
const InvestigationsPage = lazy(() =>
  import("../features/investigations/InvestigationsPage").then((m) => ({
    default: m.InvestigationsPage,
  })),
);
const LocalLabPage = lazy(() =>
  import("../features/local-lab/LocalLabPage").then((m) => ({ default: m.LocalLabPage })),
);

const PAGES: Record<string, LazyExoticComponent<() => JSX.Element>> = {
  "/metrics": MetricsPage,
  "/alerts": AlertsPage,
  "/assets": AssetsPage,
  "/sources": SourcesPage,
  "/investigations": InvestigationsPage,
  "/local-lab": LocalLabPage,
  // Ask AI used to be its own page; it's now a global slide-over (AskAiDrawer, in NavBar) that
  // every page already has. An old /ai-pilot link falls through to the Monitoring dashboard below,
  // which still carries the same "Ask AI" button.
};

export function Root() {
  const Page = PAGES[normalizePath(window.location.pathname)];
  if (Page) {
    return (
      <Suspense fallback={null}>
        <Page />
      </Suspense>
    );
  }
  return <App />;
}
