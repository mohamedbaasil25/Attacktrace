import type { LucideIcon } from "lucide-react";
import { Beaker, Bell, Compass, Radar, Radio, Search } from "lucide-react";
import { ChartColumn } from "lucide-react";

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
}

/** Top-level sections. Each is its own full page (Root.tsx's pathname switch), not a client
 *  route -- matches the project's "no react-router" constraint from CLAUDE.md. */
export const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Monitoring", icon: Radar },
  { path: "/alerts", label: "Alerts", icon: Bell },
  { path: "/assets", label: "Assets", icon: Compass },
  { path: "/investigations", label: "Investigations", icon: Search },
  { path: "/sources", label: "Sources", icon: Radio },
  { path: "/metrics", label: "Metrics", icon: ChartColumn },
  { path: "/local-lab", label: "Local lab", icon: Beaker },
];

export function normalizePath(pathname: string): string {
  const p = pathname.replace(/\/$/, "");
  return p === "" ? "/" : p;
}
