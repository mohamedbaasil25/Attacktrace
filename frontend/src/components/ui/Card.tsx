import type { ReactNode } from "react";

/** A nested content block inside a Panel (KPI tile, origin card, a split-view row group) --
 *  distinct from Panel, which owns the outer section + header. One elevation step up (bg-2). */
export function Card({
  children,
  className = "",
  as: As = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "article" | "section";
}) {
  return (
    <As
      className={`rounded-md border border-line-1 bg-surface-2 p-3 shadow-[inset_0_1px_0_var(--elevation-highlight)] ${className}`}
    >
      {children}
    </As>
  );
}
