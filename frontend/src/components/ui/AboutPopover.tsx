import { Info, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Mode } from "../../lib/types";
import { Button } from "./Button";

const MODE_MEANING: Record<Mode, string> = {
  sim: "SIM · the bundled physics simulator",
  hai: "HAI · replay of the real HAI 20.07 dataset",
  live: "LIVE · real Modbus TCP against an emulated plant",
};

/** Small, click-to-open popover (not hover: it carries real content). Closes on outside click or
 *  Escape; the trigger keeps focus-visible styling for keyboard users. */
export function AboutPopover({ mode }: { mode: Mode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        aria-label="About AttackTrace"
        aria-expanded={open}
        className="h-8 min-h-0 w-8 p-0"
        onClick={() => setOpen((v) => !v)}
      >
        <Info size={14} aria-hidden />
      </Button>
      {open && (
        <div
          role="dialog"
          aria-label="About"
          className="absolute right-0 top-8 z-20 w-64 rounded-md border border-line-2 bg-surface-2 p-3 text-label shadow-lg"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="font-medium text-ink-1">AttackTrace · by TechWizards</p>
            <button
              type="button"
              aria-label="Close"
              onClick={() => setOpen(false)}
              className="text-ink-3 hover:text-ink-1"
            >
              <X size={14} aria-hidden />
            </button>
          </div>
          <p className="mt-1 font-mono text-caption text-ink-3">v0.1.0</p>
          <p className="mt-2 text-ink-2">{MODE_MEANING[mode]}</p>
          <p className="mt-2 font-mono text-caption text-ink-3">README.md</p>
        </div>
      )}
    </div>
  );
}
