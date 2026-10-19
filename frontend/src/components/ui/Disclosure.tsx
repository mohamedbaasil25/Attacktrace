import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";
import type { ReactNode } from "react";

/** A collapsible section: a labelled header button + content region, collapsed by default.
 *  Used to keep a dense panel's primary action visible while secondary controls stay out of the
 *  way until asked for (the attack console's target/magnitude/node-scores). */
export function Disclosure({
  label,
  defaultOpen = false,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-left text-xs font-medium text-ink-3 transition-colors duration-fast ease-out hover:text-ink-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        <ChevronDown
          size={12}
          aria-hidden
          className={`transition-transform duration-fast ease-out ${open ? "" : "-rotate-90"}`}
        />
        {label}
      </button>
      {open && (
        <div id={id} className="flex flex-col gap-3">
          {children}
        </div>
      )}
    </div>
  );
}
