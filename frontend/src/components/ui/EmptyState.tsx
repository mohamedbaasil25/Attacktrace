import type { LucideIcon } from "lucide-react";

/** One icon + at most four words. */
export function EmptyState({ icon: Icon, text }: { icon: LucideIcon; text: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1 text-ink-2">
      <Icon size={24} aria-hidden />
      <span className="font-mono text-xs">{text}</span>
    </div>
  );
}
