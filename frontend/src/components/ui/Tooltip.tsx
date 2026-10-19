import type { ReactNode } from "react";

/** Hover + keyboard-focus tooltip (CSS only: `group-focus-within` fires on Tab, not just mouse).
 *  Wrap any focusable element; keep the tooltip text under ~12 words per the copy rules. */
export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group/tooltip relative inline-flex">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded-sm border border-line-2 bg-surface-3 px-2 py-1 text-caption text-ink-1 opacity-0 shadow-lg transition-opacity duration-fast ease-out group-hover/tooltip:opacity-100 group-focus-within/tooltip:opacity-100"
      >
        {label}
      </span>
    </span>
  );
}
