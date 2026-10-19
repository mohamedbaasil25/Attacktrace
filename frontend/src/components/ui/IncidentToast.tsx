import { AnimatePresence, motion } from "framer-motion";
import { ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLive } from "../../store/live";

const SHOW_MS = 4000;

/** One-line toast when a new incident opens. Follows the live stream, not the replay cursor. */
export function IncidentToast() {
  const incident = useLive((s) => s.latest?.incident ?? null);
  const [text, setText] = useState<string | null>(null);
  const seen = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (!incident) {
      seen.current = null; // after a reset the same id may come back and should toast again
      return;
    }
    if (incident.id === seen.current) return;
    seen.current = incident.id;
    setText(`${incident.id} · ${incident.origin[0]?.id ?? "unknown"}`);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setText(null), SHOW_MS);
  }, [incident]);

  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <div className="pointer-events-none fixed left-1/2 top-14 z-10 -translate-x-1/2" role="status" aria-live="polite">
      <AnimatePresence>
        {text && (
          <motion.div
            key={text}
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="flex items-center gap-2 rounded border border-origin bg-surface px-3 py-2 font-mono text-xs"
          >
            <ShieldAlert size={14} className="text-origin" aria-hidden />
            Incident {text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
