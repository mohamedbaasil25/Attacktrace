import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  icon: LucideIcon;
  className?: string;
  /** Optional controls on the right of the header. */
  actions?: ReactNode;
  children: ReactNode;
}

/** Surface with a 1 px border and a one-line header label. */
export function Panel({ title, icon: Icon, className = "", actions, children }: PanelProps) {
  return (
    <section
      aria-label={title}
      className={`flex min-h-0 min-w-0 flex-col rounded-md border border-line-1 bg-surface-1 ${className}`}
    >
      <header className="flex h-8 shrink-0 items-center gap-1 border-b border-line-1 px-2 text-xs font-medium uppercase tracking-wide text-ink-2">
        <Icon size={14} aria-hidden />
        <span>{title}</span>
        {actions && <div className="ml-auto flex items-center normal-case tracking-normal">{actions}</div>}
      </header>
      <div className="relative min-h-0 flex-1">{children}</div>
    </section>
  );
}
