import type { ReactNode } from "react";

export type Tone = "neutral" | "accent" | "normal" | "suspect" | "affected" | "origin";

const TONE: Record<Tone, string> = {
  neutral: "border-line-2 text-ink-2",
  accent: "border-accent/40 text-accent bg-accent-soft",
  normal: "border-normal/40 text-normal",
  suspect: "border-suspect/40 text-suspect",
  affected: "border-affected/40 text-affected",
  origin: "border-origin/40 text-origin",
};

/** A small labelled pill: MITRE id, mode tag ("Emulated plant", "Replay"), delta badge. Never
 *  colour alone -- always carries its own text. */
export function Chip({
  tone = "neutral",
  icon,
  children,
  title,
  testId,
}: {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
  title?: string;
  testId?: string;
}) {
  return (
    <span
      title={title}
      data-testid={testId}
      className={`inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 font-mono text-caption uppercase tracking-[0.04em] ${TONE[tone]}`}
    >
      {icon}
      {children}
    </span>
  );
}
