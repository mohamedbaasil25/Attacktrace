import type { NodeStatus } from "../../lib/types";

export const STATUS_COLOR: Record<NodeStatus, string> = {
  normal: "var(--normal)",
  suspect: "var(--suspect)",
  affected: "var(--affected)",
  origin: "var(--origin)",
};

export const STATUS_LABEL: Record<NodeStatus, string> = {
  normal: "Normal",
  suspect: "Suspect",
  affected: "Affected",
  origin: "Origin",
};
