import type { ReactNode } from "react";
import { CHAR_W, TEXT, VIEW } from "./geometry";

interface Props {
  /** Where the detail text's top-left corner would sit; clamped to stay inside the viewBox so a
   *  badge near the top/right edge doesn't push its popup off-canvas (the SVG clips by default). */
  at: { x: number; y: number };
  text: string;
  children: ReactNode;
}

/** Wraps SVG twin content with a keyboard-reachable hover/focus detail popup. A bare SVG
 *  `<title>` only ever shows on mouse hover, so anything it alone carried was invisible to
 *  keyboard-only sighted users (Phase 15 Part B audit finding, fixed here): this makes the host
 *  shape focusable, gives it a matching `aria-label` for assistive tech, and shows the same text
 *  as a visible popup on hover *or* keyboard focus. */
export function HoverLabel({ at, text, children }: Props) {
  const w = text.length * (CHAR_W * 0.62) + 10;
  const h = TEXT + 6;
  const x = Math.min(Math.max(at.x, 2), VIEW.w - w - 2);
  const y = Math.min(Math.max(at.y, 2), VIEW.h - h - 2);
  return (
    <g
      tabIndex={0}
      aria-label={text}
      className="group/hint cursor-help outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
    >
      <title>{text}</title>
      {children}
      <g className="pointer-events-none opacity-0 transition-opacity duration-fast ease-out group-hover/hint:opacity-100 group-focus-visible/hint:opacity-100">
        <rect x={x} y={y} width={w} height={h} rx={4} fill="var(--bg-3)" stroke="var(--line-2)" />
        <text x={x + 5} y={y + TEXT - 1} fontSize={TEXT * 0.64} className="fill-ink-1 font-mono">
          {text}
        </text>
      </g>
    </g>
  );
}
