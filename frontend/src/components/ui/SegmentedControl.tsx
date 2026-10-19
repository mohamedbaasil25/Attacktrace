import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";

export interface Segment<T extends string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
  title?: string;
}

interface Props<T extends string> {
  value: T;
  segments: ReadonlyArray<Segment<T>>;
  onChange: (v: T) => void;
  "aria-label": string;
  /** Framer Motion layoutId is global to the page, not scoped to this instance -- two
   *  SegmentedControls on screen at once (e.g. the top bar's mode toggle and a stage-view toggle)
   *  need distinct ids or their sliding indicators cross-animate into each other. */
  layoutId?: string;
}

/** A labelled group of mutually-exclusive options with one sliding active indicator (Framer
 *  Motion `layoutId`, so the slide is a single shared-element animation, not per-button state). */
export function SegmentedControl<T extends string>({
  value,
  segments,
  onChange,
  "aria-label": ariaLabel,
  layoutId = "segmented-indicator",
}: Props<T>) {
  const reduce = useReducedMotion();
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex rounded-md border border-line-1 bg-surface-1 p-0.5"
    >
      {segments.map((s) => {
        const active = s.value === value;
        return (
          <button
            key={s.value}
            type="button"
            aria-pressed={active}
            disabled={s.disabled}
            title={s.title}
            onClick={() => onChange(s.value)}
            className="relative h-8 min-w-[44px] rounded-sm px-2 font-mono text-caption uppercase tracking-[0.04em] text-ink-2 transition-colors duration-fast ease-out hover:text-ink-1 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-ink-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
          >
            {active && (
              <motion.span
                layoutId={layoutId}
                className="absolute inset-0 rounded-sm bg-accent"
                transition={reduce ? { duration: 0 } : { duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
              />
            )}
            <span className={`relative ${active ? "text-surface-0" : ""}`}>{s.label}</span>
          </button>
        );
      })}
    </div>
  );
}
